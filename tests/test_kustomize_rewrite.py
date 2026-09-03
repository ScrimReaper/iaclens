from pathlib import Path

from infra_graph.parsers.yaml_parser import YAMLParser

FX = Path(__file__).parent / "fixtures" / "kustomize_repo"


def _graph(root):
    p = YAMLParser(root)
    nodes, edges = [], []
    for f in sorted(root.rglob("*.y*ml")):
        r = p.parse_file(f)
        nodes += r["nodes"]
        edges += r["edges"]
    edges += p.finalize()
    return nodes, edges


def test_same_named_overlays_do_not_collide():
    nodes, _ = _graph(FX)
    ov = [n["id"] for n in nodes if n["type"] == "kustomize" and n["kind"] == "overlay"]
    assert len(ov) == len(set(ov))
    assert "kustomize/apps/foo/overlays/production" in ov
    assert "kustomize/apps/bar/overlays/production" in ov
