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


def test_legitimate_uses_var_edge_survives_the_drop(tmp_path):
    proj = tmp_path / "proj"
    shutil.copytree(_FIXTURE, proj)
    builder = GraphBuilder(proj)
    builder.build()
    assert any(
        d.get("type") == "uses_var"
        and f.endswith("#aws_instance.web")
        and t.endswith("#name")
        for f, t, d in builder.graph.edges(data=True)
    ), "the var.name reference inside templatefile(...) args must still link"


def test_bare_module_ref_is_a_module_edge_not_a_resource():
    edge_type, target = _classify_interp("module.net", ".")
    assert edge_type == "uses_module"
    assert target == "module/.#net"


def test_dynamic_exprs_link_their_inner_refs_instead_of_stubbing(tmp_path):
    """`format("%s-web", var.name)` or `local.n + 1` used to become ONE
    `dynamic_ref` edge whose target was the raw expression, i.e. a typeless
    `unknown` node named after the expression. The references inside the
    expression are what matters: link to them (still marked AMBIGUOUS) and
    never create the expression node."""
    proj = tmp_path / "proj"
    shutil.copytree(_FIXTURE, proj)
    builder = GraphBuilder(proj)
    builder.build()

    ids = set(builder.graph.nodes())
    assert not [n for n in ids if any(c in n for c in " (+\"")], "expression ids leaked"
    assert not [n for n, a in builder.graph.nodes(data=True) if a.get("type") == "unknown"]

    dyn = {
        (f.split("#")[-1], t.split("/")[0], t.split("#")[-1])
        for f, t, d in builder.graph.edges(data=True)
        if d.get("type") == "dynamic_ref"
    }
    assert ("label", "variable", "name") in dyn
    assert ("count2", "local", "n") in dyn
    assert ("joined", "resource", "aws_instance.web") in dyn
    assert ("joined", "variable", "name") in dyn
    for f, t, d in builder.graph.edges(data=True):
        if d.get("type") == "dynamic_ref":
            assert d["provenance"] == "AMBIGUOUS" and d["confidence"] == 0.5

    assert any(
        d.get("type") == "uses_module" and t == "module/.#net"
        for _, t, d in builder.graph.edges(data=True)
    )
