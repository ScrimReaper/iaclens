"""Tests for the Terraform parser."""

from pathlib import Path

import pytest

from infra_graph.parsers.tf_parser import TerraformParser

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture()
def tf_result():
    parser = TerraformParser(FIXTURES)
    return parser.parse_file(FIXTURES / "sample.tf")


def test_parse_returns_nodes_and_edges(tf_result):
    assert "nodes" in tf_result
    assert "edges" in tf_result
    assert len(tf_result["nodes"]) > 0
    assert len(tf_result["edges"]) > 0


def test_resource_nodes_extracted(tf_result):
    node_ids = {n["id"] for n in tf_result["nodes"]}
    assert "resource/.#aws_vpc.main" in node_ids
    assert "resource/.#aws_subnet.public" in node_ids
    assert "resource/.#aws_instance.web_server" in node_ids


def test_variable_nodes_extracted(tf_result):
    node_ids = {n["id"] for n in tf_result["nodes"]}
    assert "variable/.#region" in node_ids
    assert "variable/.#environment" in node_ids


def test_data_node_extracted(tf_result):
    node_ids = {n["id"] for n in tf_result["nodes"]}
    assert "data/.#aws_ami.ubuntu" in node_ids


def test_output_nodes_extracted(tf_result):
    node_ids = {n["id"] for n in tf_result["nodes"]}
    assert "output/.#vpc_id" in node_ids
    assert "output/.#web_server_ip" in node_ids


def test_local_node_extracted(tf_result):
    node_ids = {n["id"] for n in tf_result["nodes"]}
    assert "local/.#common_tags" in node_ids


def test_provider_node_extracted(tf_result):
    node_ids = {n["id"] for n in tf_result["nodes"]}
    assert "provider/.#aws" in node_ids


def test_depends_on_edges(tf_result):
    """aws_subnet.public and aws_instance.web_server have explicit depends_on."""
    depends_edges = [
        e for e in tf_result["edges"]
        if e["type"] == "depends_on"
    ]
    assert len(depends_edges) >= 2

    edge_pairs = {(e["from"], e["to"]) for e in depends_edges}
    # aws_subnet.public depends_on aws_vpc.main
    assert ("resource/.#aws_subnet.public", "resource/.#aws_vpc.main") in edge_pairs
    # aws_instance.web_server depends_on aws_subnet.public
    assert ("resource/.#aws_instance.web_server", "resource/.#aws_subnet.public") in edge_pairs


def test_uses_var_edges(tf_result):
    """Resources referencing var.environment should have uses_var edges."""
    uses_var_edges = [e for e in tf_result["edges"] if e["type"] == "uses_var"]
    targets = {e["to"] for e in uses_var_edges}
    # var.environment is referenced in aws_vpc and aws_instance tags
    assert "variable/.#environment" in targets


def test_uses_data_edges(tf_result):
    """aws_instance.web_server references data.aws_ami.ubuntu."""
    uses_data_edges = [e for e in tf_result["edges"] if e["type"] == "uses_data"]
    assert len(uses_data_edges) >= 1
    targets = {e["to"] for e in uses_data_edges}
    assert "data/.#aws_ami.ubuntu" in targets


def test_references_edges(tf_result):
    """aws_subnet.public references aws_vpc.main.id via interpolation."""
    ref_edges = [e for e in tf_result["edges"] if e["type"] == "references"]
    pairs = {(e["from"], e["to"]) for e in ref_edges}
    assert ("resource/.#aws_subnet.public", "resource/.#aws_vpc.main") in pairs


def test_node_schema(tf_result):
    """Every node must have required schema fields."""
    required_fields = {"id", "type", "kind", "name", "file", "line", "labels"}
    for node in tf_result["nodes"]:
        missing = required_fields - set(node.keys())
        assert not missing, f"Node {node.get('id')} missing fields: {missing}"


def test_edge_schema(tf_result):
    """Every edge must have required schema fields."""
    required_fields = {"from", "to", "type", "confidence", "provenance"}
    for edge in tf_result["edges"]:
        missing = required_fields - set(edge.keys())
        assert not missing, f"Edge missing fields: {missing}"


def test_edge_provenance_values(tf_result):
    """All edges have valid provenance values."""
    valid = {"EXTRACTED", "INFERRED", "AMBIGUOUS"}
    for edge in tf_result["edges"]:
        assert edge["provenance"] in valid, f"Invalid provenance: {edge['provenance']}"


def test_confidence_range(tf_result):
    """Confidence values should be between 0 and 1."""
    for edge in tf_result["edges"]:
        assert 0.0 <= edge["confidence"] <= 1.0


def test_node_file_set(tf_result):
    """All nodes parsed from a file should have the file path set."""
    for node in tf_result["nodes"]:
        assert node["file"] is not None
        assert node["file"].endswith("sample.tf")


def test_dynamic_ref_edges(tf_result):
    """Interpolations with ${var.region}a should produce a dynamic_ref or uses_var edge."""
    # aws_subnet uses "${var.region}a" — concatenation → dynamic_ref
    # OR it might be classified as uses_var depending on regex handling
    all_types = {e["type"] for e in tf_result["edges"]}
    assert "uses_var" in all_types or "dynamic_ref" in all_types


def test_parse_nonexistent_file():
    """Parsing a nonexistent file should return empty nodes/edges (not crash)."""
    parser = TerraformParser(FIXTURES)
    result = parser.parse_file(Path("/nonexistent/path.tf"))
    assert result["nodes"] == []
    assert result["edges"] == []
