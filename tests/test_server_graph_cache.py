"""The MCP server re-reads the graph file only when it changed on disk,
instead of parsing it again on every tool call."""

from __future__ import annotations

import networkx as nx

from infra_graph.graph import toon
from infra_graph.mcp import server
from infra_graph.mcp import tools as T


def _write(path, n):
    g = nx.DiGraph()
    for i in range(n):
        g.add_node(f"n{i}", type="t")
    toon.dump_graph(g, path, {})


def test_cache_loads_once_until_file_changes(tmp_path, monkeypatch):
    gf = tmp_path / "graph.toon"
    _write(gf, 2)
    calls = {"n": 0}
    real = server.toon.load_graph

    def counted(p):
        calls["n"] += 1
        return real(p)

    monkeypatch.setattr(server.toon, "load_graph", counted)
    cache = server.GraphCache(tmp_path, graph_file=gf)
    assert cache.get().number_of_nodes() == 2
    assert cache.get().number_of_nodes() == 2
    assert calls["n"] == 1

    _write(gf, 3)
    assert cache.get().number_of_nodes() == 3
    assert calls["n"] == 2


def test_cache_falls_back_to_out_dir(tmp_path):
    out = tmp_path / "iaclens-out"
    out.mkdir()
    _write(out / "graph.toon", 1)
    assert server.GraphCache(tmp_path).get().number_of_nodes() == 1


def test_cache_is_empty_when_no_graph_and_picks_up_a_later_build(tmp_path):
    cache = server.GraphCache(tmp_path)
    assert cache.get().number_of_nodes() == 0
    out = tmp_path / "iaclens-out"
    out.mkdir()
    _write(out / "graph.toon", 1)
    assert cache.get().number_of_nodes() == 1


def test_cache_keeps_last_good_graph_when_file_is_unreadable(tmp_path):
    """A half-written or corrupt file must not blank the served graph; the
    previous graph stays until a good file appears."""
    gf = tmp_path / "graph.toon"
    _write(gf, 2)
    cache = server.GraphCache(tmp_path, graph_file=gf)
    assert cache.get().number_of_nodes() == 2

    gf.write_bytes(b"\xff\xfe not toon")
    assert cache.get().number_of_nodes() == 2

    _write(gf, 4)
    assert cache.get().number_of_nodes() == 4


def test_build_tool_reports_the_file_it_wrote(tmp_path):
    (tmp_path / "conf.yml").write_text("a: 1\n")
    result = T.build_or_update_graph(str(tmp_path))
    assert result["success"] is True
    assert result["graph_file"].endswith("graph.toon")
    assert (tmp_path / "iaclens-out" / "graph.toon").exists()


def test_dispatch_build_tool_uses_the_workspace_for_served_roots(tmp_path):
    from infra_graph.workspace import Workspace

    a = tmp_path / "a"
    a.mkdir()
    (a / "conf.yml").write_text("a: 1\n")
    ws = Workspace([a])
    ws.build_all()
    (a / "more.yml").write_text("b: 2\n")

    result = server._dispatch(
        ws.get(), "build_or_update_graph", {"path": str(a)}, a, source=ws
    )
    assert result["success"] is True
    assert result["federated"] is True
    assert any(n.endswith("#more") for n in ws.get().nodes)


def test_dispatch_build_tool_falls_back_for_foreign_paths(tmp_path):
    from infra_graph.workspace import Workspace

    a, other = tmp_path / "a", tmp_path / "other"
    a.mkdir()
    other.mkdir()
    (a / "conf.yml").write_text("a: 1\n")
    (other / "conf.yml").write_text("z: 1\n")
    ws = Workspace([a])
    ws.build_all()

    result = server._dispatch(
        ws.get(), "build_or_update_graph", {"path": str(other)}, a, source=ws
    )
    assert result["success"] is True
    assert "not one of the served roots" in result["note"]
