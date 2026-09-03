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


def test_module_output_ref_resolves_to_child_output():
    p = TerraformParser(FX)
    edges = []
    for f in sorted(FX.rglob("*.tf")):
        edges += p.parse_file(f)["edges"]
    edges += p.finalize()
    trip = [(e["from"], e["to"], e["type"]) for e in edges]
    assert (
        "resource/.#aws_eip.x",
        "output/modules/net#subnet_id",
        "uses_module_output",
    ) in trip
    # module input wiring
    assert ("module/.#net", "variable/modules/net#region", "passes_input") in trip


def test_resource_records_count_and_for_each():
    nodes, edges = _graph(FX)
    by = {n["id"]: n for n in nodes}
    assert by["resource/.#aws_instance.web"]["labels"].get("count") is not None
    assert by["resource/.#aws_s3_bucket.b"]["labels"].get("for_each") is not None
    # no edges are created for these
    counted_edges = [
        e for e in edges if e["from"] in ("resource/.#aws_instance.web", "resource/.#aws_s3_bucket.b")
    ]
    assert counted_edges == []
