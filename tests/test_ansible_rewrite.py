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
