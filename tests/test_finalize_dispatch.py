from pathlib import Path

from infra_graph.parsers.yaml_parser import YAMLParser


def test_finalize_collects_subparser_edges(monkeypatch):
    p = YAMLParser(Path("/repo"))
    # inject a fake finalize on the ansible sub-parser
    p._ansible.finalize = lambda: [{"from": "a", "to": "b", "type": "test"}]  # type: ignore[attr-defined]
    edges = p.finalize()
    assert {"from": "a", "to": "b", "type": "test"} in edges
