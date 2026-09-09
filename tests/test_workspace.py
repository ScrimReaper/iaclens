"""`iaclens serve --path A --path B` serves several repos as ONE federated
graph, rebuilt per root and re-federated in-process, so a federated graph
stays fresh without an external rebuild-all + re-federate script."""

from __future__ import annotations

from pathlib import Path

from infra_graph.graph import toon
from infra_graph.workspace import Workspace


def _k8s(root: Path, name: str, kind: str = "Deployment") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    f = root / f"{name}.yaml"
    f.write_text(
        f"apiVersion: apps/v1\nkind: {kind}\nmetadata:\n  name: {name}\n"
        f"  namespace: default\n  labels:\n    app: {name}\nspec: {{}}\n"
    )
    return f


def _names(graph) -> set[str]:
    return {a.get("name") for _, a in graph.nodes(data=True)}


def test_build_all_federates_every_root(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    _k8s(a, "alpha")
    _k8s(b, "beta")
    ws = Workspace([a, b])
    stats = ws.build_all()
    assert _names(ws.get()) >= {"alpha", "beta"}
    assert stats["source_count"] == 2
    assert stats["nodes"] == ws.get().number_of_nodes()
    # each root still gets its own per-repo graph for the CLI
    assert (a / "iaclens-out" / "graph.toon").exists()
    assert (b / "iaclens-out" / "graph.toon").exists()


def test_shared_node_is_merged_once(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    _k8s(a, "shared")
    _k8s(b, "shared")
    ws = Workspace([a, b])
    ws.build_all()
    ids = [n for n in ws.get().nodes if n.endswith("/shared")]
    assert len(ids) == 1


def test_rebuild_one_root_refreshes_the_federated_graph(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    _k8s(a, "alpha")
    _k8s(b, "beta")
    ws = Workspace([a, b])
    ws.build_all()
    before = ws.get()

    _k8s(b, "gamma")
    ws.rebuild([b])
    after = ws.get()
    assert after is not before, "a rebuild publishes a new graph object"
    assert "gamma" in _names(after)
    assert "alpha" in _names(after), "untouched roots keep their nodes"


def test_root_for_maps_nested_paths_to_their_root(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    _k8s(a, "alpha")
    _k8s(b, "beta")
    ws = Workspace([a, b])
    assert ws.root_for(a / "deep" / "x.yaml") == a.resolve()
    assert ws.root_for(b / "beta.yaml") == b.resolve()
    assert ws.root_for(tmp_path / "elsewhere.yaml") is None


def test_dirty_roots_are_rebuilt_on_flush_only(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    _k8s(a, "alpha")
    _k8s(b, "beta")
    ws = Workspace([a, b])
    ws.build_all()
    built: list[Path] = []
    real = ws.rebuild
    ws.rebuild = lambda roots: (built.extend(roots), real(roots))[1]  # type: ignore[method-assign]

    ws.mark_dirty(str(b / "beta.yaml"))
    ws.mark_dirty(str(b / "other.yaml"))
    ws.mark_dirty(str(tmp_path / "outside.yaml"))  # not a root: ignored
    ws.flush_dirty()
    assert built == [b.resolve()]

    built.clear()
    ws.flush_dirty()  # nothing dirty: no rebuild at all
    assert built == []


def test_rebuild_path_only_for_served_roots(tmp_path):
    a = tmp_path / "a"
    _k8s(a, "alpha")
    ws = Workspace([a])
    ws.build_all()
    assert ws.rebuild_path(tmp_path / "not-a-root") is None
    _k8s(a, "delta")
    result = ws.rebuild_path(a)
    assert result is not None
    assert "delta" in _names(ws.get())


def test_out_file_is_written_after_each_federation(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    _k8s(a, "alpha")
    _k8s(b, "beta")
    out = tmp_path / "fed" / "workspace.toon"
    ws = Workspace([a, b], out_file=out)
    ws.build_all()
    g, meta = toon.load_graph(out)
    assert _names(g) >= {"alpha", "beta"}
    assert meta.get("federated") == "True"

    _k8s(b, "gamma")
    ws.rebuild([b])
    g, _ = toon.load_graph(out)
    assert "gamma" in _names(g)


def test_out_file_json_by_suffix(tmp_path):
    import json

    a = tmp_path / "a"
    _k8s(a, "alpha")
    out = tmp_path / "workspace.json"
    Workspace([a], out_file=out).build_all()
    data = json.loads(out.read_text())
    assert any(n["name"] == "alpha" for n in data["nodes"])
    assert data["meta"]["federated"] is True
