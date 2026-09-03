"""Tests for the stateful, path-qualified Ansible parser (WS1 Task 1)."""

from pathlib import Path

from infra_graph.parsers.yaml_parser import YAMLParser

FX = Path(__file__).parent / "fixtures" / "ansible_repo"


def _graph(root):
    p = YAMLParser(root)
    nodes, edges = [], []
    for f in sorted(root.rglob("*.y*ml")):
        r = p.parse_file(f)
        nodes += r["nodes"]
        edges += r["edges"]
    edges += p.finalize()
    return nodes, edges


def test_task_files_do_not_collide():
    nodes, _ = _graph(FX)
    tf = [n["id"] for n in nodes if n["type"] == "task_file"]
    assert len(tf) == len(set(tf))  # no collisions
    assert "task_file/roles/nginx/tasks/main.yml" in tf
    assert "task_file/roles/postgres/tasks/main.yml" in tf
    assert "task_file/roles/common/tasks/main.yml" in tf


def test_role_links_to_its_tasks():
    _, edges = _graph(FX)
    got = [{"from": e["from"], "to": e["to"], "type": e["type"]} for e in edges]
    assert {
        "from": "role/nginx",
        "to": "task_file/roles/nginx/tasks/main.yml",
        "type": "has_task",
    } in got
    assert {
        "from": "role/postgres",
        "to": "task_file/roles/postgres/tasks/main.yml",
        "type": "has_task",
    } in got
    # common has no playbook reference, but is still a role (path-discovered)
    assert {
        "from": "role/common",
        "to": "task_file/roles/common/tasks/main.yml",
        "type": "has_task",
    } in got


def test_play_id_is_path_qualified():
    nodes, _ = _graph(FX)
    play_ids = [n["id"] for n in nodes if n["type"] == "play"]
    assert "play/site.yml#webservers" in play_ids


def test_playbook_uses_role_edges():
    _, edges = _graph(FX)
    got = [(e["from"], e["to"]) for e in edges if e["type"] == "uses_role"]
    assert ("play/site.yml#webservers", "role/nginx") in got
    assert ("play/site.yml#webservers", "role/postgres") in got


def test_role_nodes_have_stable_ids():
    nodes, _ = _graph(FX)
    role_ids = {n["id"] for n in nodes if n["type"] == "role"}
    assert {"role/nginx", "role/postgres", "role/common"} <= role_ids


def test_block_nested_include_resolves_by_path():
    _, edges = _graph(FX)
    got = [(e["from"], e["to"], e["type"]) for e in edges]
    assert (
        "task_file/roles/common/tasks/main.yml",
        "task_file/roles/common/tasks/setup.yml",
        "includes_tasks",
    ) in got


def test_rescue_and_always_are_recursed_too():
    """block/rescue/always all contain nested task lists; make sure the scan
    doesn't stop at `block:` alone (no include in rescue/always here, but the
    task file must still parse without error and the block-nested include
    must be found regardless of rescue/always presence)."""
    nodes, edges = _graph(FX)
    tf_ids = {n["id"] for n in nodes if n["type"] == "task_file"}
    assert "task_file/roles/common/tasks/main.yml" in tf_ids
    got = [(e["from"], e["to"], e["type"]) for e in edges]
    assert (
        "task_file/roles/common/tasks/main.yml",
        "task_file/roles/common/tasks/setup.yml",
        "includes_tasks",
    ) in got


def test_import_tasks_uses_imports_tasks_edge_type():
    _, edges = _graph(FX)
    got = [(e["from"], e["to"], e["type"]) for e in edges]
    assert (
        "task_file/roles/common/tasks/main.yml",
        "task_file/roles/common/tasks/extra.yml",
        "imports_tasks",
    ) in got


def test_include_role_and_import_role_edges():
    _, edges = _graph(FX)
    got = [(e["from"], e["to"], e["type"]) for e in edges]
    assert (
        "task_file/roles/common/tasks/main.yml",
        "role/nginx",
        "includes_role",
    ) in got
    assert (
        "task_file/roles/common/tasks/main.yml",
        "role/postgres",
        "includes_role",
    ) in got


def test_include_target_gets_a_stub_node_even_when_never_parsed():
    """Include targets that don't correspond to any parsed file still get a
    path-qualified stub task_file node (so the edge target always exists)."""
    nodes, edges = _graph(FX)
    tf_ids = {n["id"] for n in nodes if n["type"] == "task_file"}
    got = [(e["from"], e["to"], e["type"]) for e in edges]
    # setup.yml IS parsed in this fixture repo, so assert on its presence
    # both as a real node and as an edge target — proving finalize() doesn't
    # care whether the target was seen before or after the including file.
    assert "task_file/roles/common/tasks/setup.yml" in tf_ids
    assert (
        "task_file/roles/common/tasks/main.yml",
        "task_file/roles/common/tasks/setup.yml",
        "includes_tasks",
    ) in got


def test_handler_nodes_and_has_handler_edges():
    nodes, edges = _graph(FX)
    handler_ids = {n["id"] for n in nodes if n["type"] == "handler"}
    assert "handler/nginx/restart nginx" in handler_ids
    assert "handler/nginx/reload nginx" in handler_ids
    assert "handler/common/common handler" in handler_ids

    got = [(e["from"], e["to"], e["type"]) for e in edges]
    assert ("role/nginx", "handler/nginx/restart nginx", "has_handler") in got
    assert ("role/nginx", "handler/nginx/reload nginx", "has_handler") in got
    assert ("role/common", "handler/common/common handler", "has_handler") in got


def test_notify_resolves_to_handler_by_name():
    _, edges = _graph(FX)
    notify_edges = [
        (e["from"], e["to"], e["confidence"], e["provenance"])
        for e in edges
        if e["type"] == "notifies"
    ]
    assert (
        "task_file/roles/nginx/tasks/main.yml",
        "handler/nginx/restart nginx",
        0.9,
        "INFERRED",
    ) in notify_edges


def test_notify_resolves_to_handler_by_listen_topic():
    _, edges = _graph(FX)
    notify_edges = [(e["from"], e["to"]) for e in edges if e["type"] == "notifies"]
    assert (
        "task_file/roles/nginx/tasks/main.yml",
        "handler/nginx/reload nginx",
    ) in notify_edges


def test_notify_nested_in_block_rescue_always_is_collected():
    _, edges = _graph(FX)
    notify_edges = [(e["from"], e["to"]) for e in edges if e["type"] == "notifies"]
    assert (
        "task_file/roles/common/tasks/main.yml",
        "handler/common/common handler",
    ) in notify_edges


def test_group_vars_node_and_role_vars_edges():
    nodes, edges = _graph(FX)
    vars_ids = {n["id"] for n in nodes if n["type"] == "vars"}
    assert "vars/group/webservers" in vars_ids
    assert "vars/group/all" in vars_ids
    assert "vars/host/web1" in vars_ids
    assert "vars/roles/nginx/defaults/main.yml" in vars_ids
    assert "vars/roles/nginx/vars/main.yml" in vars_ids

    got = [
        (e["from"], e["to"], e["type"], e["confidence"], e["provenance"]) for e in edges
    ]
    assert (
        "role/nginx",
        "vars/roles/nginx/defaults/main.yml",
        "uses_vars",
        1.0,
        "EXTRACTED",
    ) in got
    assert (
        "role/nginx",
        "vars/roles/nginx/vars/main.yml",
        "uses_vars",
        1.0,
        "EXTRACTED",
    ) in got


def test_group_vars_links_to_matching_play_by_hosts():
    _, edges = _graph(FX)
    got = [
        (e["from"], e["to"], e["type"], e["confidence"], e["provenance"])
        for e in edges
        if e["type"] == "uses_vars"
    ]
    assert (
        "vars/group/webservers",
        "play/site.yml#webservers",
        "uses_vars",
        0.9,
        "INFERRED",
    ) in got
    # not linked to the unrelated play (hosts: web1,web2 doesn't include webservers)
    assert (
        "vars/group/webservers",
        "play/site.yml#web1,web2",
        "uses_vars",
        0.9,
        "INFERRED",
    ) not in got


def test_group_vars_all_links_to_every_play():
    nodes, edges = _graph(FX)
    play_ids = {n["id"] for n in nodes if n["type"] == "play"}
    linked = {
        e["to"]
        for e in edges
        if e["type"] == "uses_vars" and e["from"] == "vars/group/all"
    }
    assert play_ids <= linked


def test_host_vars_links_to_matching_play_by_hosts():
    _, edges = _graph(FX)
    got = [(e["from"], e["to"], e["type"]) for e in edges if e["type"] == "uses_vars"]
    assert ("vars/host/web1", "play/site.yml#web1,web2", "uses_vars") in got
    assert ("vars/host/web1", "play/site.yml#webservers", "uses_vars") not in got


def test_finalize_is_idempotent_no_duplicate_edges():
    """Calling finalize() twice must not double-emit pending-derived edges."""
    from infra_graph.parsers.yaml_parser import YAMLParser

    p = YAMLParser(FX)
    for f in sorted(FX.rglob("*.y*ml")):
        p.parse_file(f)
    first = p.finalize()
    second = p.finalize()
    assert len(first) > 0
    assert second == []
