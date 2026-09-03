from pathlib import Path

from infra_graph.parsers._ids import qualified, rel_posix


def test_rel_posix_under_root():
    root = Path("/repo")
    assert rel_posix(Path("/repo/roles/nginx/tasks/main.yml"), root) == "roles/nginx/tasks/main.yml"


def test_rel_posix_outside_root_falls_back_to_name():
    assert rel_posix(Path("/other/x.tf"), Path("/repo")) == "x.tf"


def test_qualified_format():
    assert qualified("config", "envs/prod/app.yml", "app") == "config/envs/prod/app.yml#app"
