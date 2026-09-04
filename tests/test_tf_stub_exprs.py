# tests/test_tf_stub_exprs.py
"""The tofu parser drops unresolvable interpolation targets instead of
emitting bogus references that become typeless `unknown` stub nodes."""

import shutil
from pathlib import Path

from infra_graph.graph.builder import GraphBuilder
from infra_graph.parsers.tf_parser import _classify_interp


def test_clean_resource_ref_still_emits():
    edge_type, target = _classify_interp("aws_vpc.main.id", ".")
    assert edge_type == "references"
    assert target.endswith("#aws_vpc.main")


def test_two_segment_resource_ref_still_emits():
    edge_type, target = _classify_interp("aws_vpc.main", ".")
    assert edge_type == "references"
    assert target.endswith("#aws_vpc.main")


def test_var_ref_unchanged():
    edge_type, target = _classify_interp("var.name", ".")
    assert edge_type == "uses_var"
    assert target.endswith("#name")


def test_path_module_is_dropped():
    assert _classify_interp("path.module", ".") == ("", "")


def test_terraform_and_self_are_dropped():
    assert _classify_interp("terraform.workspace", ".") == ("", "")
    assert _classify_interp("self.private_ip", ".") == ("", "")


def test_templatefile_fragment_is_dropped():
    # this is the mangled fragment _INTERP_RE actually extracts from a
    # templatefile("${path.module}/init.tpl", ...) call
    assert _classify_interp('templatefile("${path.module', ".") == ("", "")


def test_for_comprehension_is_dropped():
    assert _classify_interp("[for m in module.vm : m.id]", ".") == ("", "")
    assert _classify_interp("[for m in aws_instance.web : m", ".") == ("", "")


_FIXTURE = Path(__file__).parent / "fixtures" / "tf_stub_exprs"


def test_unresolvable_exprs_make_no_unknown_nodes(tmp_path):
    proj = tmp_path / "proj"
    shutil.copytree(_FIXTURE, proj)
    builder = GraphBuilder(proj)
    builder.build()

    node_ids = set(builder.graph.nodes())
    # the fixture actually parsed (guards against a vacuous pass)
    assert any(nid.endswith("#aws_instance.web") for nid in node_ids)

    unknown = [
        nid for nid, attrs in builder.graph.nodes(data=True)
        if attrs.get("type") == "unknown"
    ]
    assert not unknown, f"typeless stub nodes present: {unknown}"

    garbage = [nid for nid in node_ids if any(c in nid for c in '("[')]
    assert not garbage, f"garbage-charactered node ids present: {garbage}"
