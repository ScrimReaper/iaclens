from pathlib import Path

from infra_graph.parsers.tf_parser import TerraformParser
from infra_graph.parsers.yaml_parser import YAMLParser


def test_parsers_store_root():
    root = Path("/repo")
    assert YAMLParser(root)._root == root.resolve()
    assert TerraformParser(root)._root == root.resolve()
