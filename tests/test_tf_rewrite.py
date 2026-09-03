"""Tests for directory-qualified Terraform node IDs and same-dir ref resolution."""

from pathlib import Path

from infra_graph.parsers.tf_parser import TerraformParser

FX = Path(__file__).parent / "fixtures" / "tf_repo"


def _graph(root):
    p = TerraformParser(root)
    nodes, edges = [], []
    for f in sorted(root.rglob("*.tf")):
        r = p.parse_file(f)
        nodes += r["nodes"]
        edges += r["edges"]
    return nodes, edges


def test_same_named_vars_in_different_modules_do_not_collide():
    nodes, _ = _graph(FX)
    var_ids = [n["id"] for n in nodes if n["type"] == "variable"]
    assert "variable/.#region" in var_ids
    assert "variable/modules/net#region" in var_ids
    assert len(var_ids) == len(set(var_ids))


def test_var_ref_resolves_within_same_module():
    _, edges = _graph(FX)
    trip = [(e["from"], e["to"], e["type"]) for e in edges]
    assert (
        "resource/modules/net#aws_subnet.a",
        "variable/modules/net#region",
        "uses_var",
    ) in trip
