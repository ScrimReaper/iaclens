"""A Jinja-templated docker-compose.yml (Ansible role template) must be skipped
quietly, not warned about — regression for the aviloo-ansible nexus template."""

import warnings

from infra_graph.parsers.compose_schema import ComposeParser

_JINJA = "services:\n  nexus:\n{% if nexus_add_vm_params %}\n    env: prod\n{% endif %}\n"


def test_templated_compose_under_templates_dir_is_skipped_silently(tmp_path):
    d = tmp_path / "roles" / "nexus" / "templates"
    d.mkdir(parents=True)
    f = d / "docker-compose.yml"
    f.write_text(_JINJA)
    p = ComposeParser()
    assert p.is_compose_file(f) is True  # still matched by filename
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # any warning fails the test
        result = p.parse_file(f)
    assert result == {"nodes": [], "edges": []}


def test_jinja_compose_outside_templates_dir_is_skipped_silently(tmp_path):
    f = tmp_path / "docker-compose.yml"
    f.write_text(_JINJA)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        result = ComposeParser().parse_file(f)
    assert result == {"nodes": [], "edges": []}


def test_plain_compose_still_parses(tmp_path):
    f = tmp_path / "docker-compose.yml"
    f.write_text("services:\n  web:\n    image: nginx\nvolumes:\n  data: {}\n")
    result = ComposeParser().parse_file(f)
    ids = [n["id"] for n in result["nodes"]]
    assert any(i.startswith("service/") for i in ids)
    assert any(i.startswith("volume/") for i in ids)
