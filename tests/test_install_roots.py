"""`iaclens install --root A --root B` wires a multi-root serve entry."""

import json
from pathlib import Path

from click.testing import CliRunner

from infra_graph.cli import cli
from infra_graph.install.claude import install


def test_install_roots_writes_multi_root_serve(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    install(tmp_path, roots=[a, b])
    cfg = json.loads((tmp_path / ".mcp.json").read_text())
    args = cfg["mcpServers"]["iaclens"]["args"]
    assert args == ["serve", "--path", str(a.resolve()), "--path", str(b.resolve())]


def test_install_without_roots_keeps_plain_serve(tmp_path):
    install(tmp_path)
    cfg = json.loads((tmp_path / ".mcp.json").read_text())
    assert cfg["mcpServers"]["iaclens"]["args"] == ["serve"]


def test_install_cli_accepts_repeated_root(tmp_path):
    a = tmp_path / "a"
    a.mkdir()
    result = CliRunner().invoke(cli, ["install", "--path", str(tmp_path), "--root", str(a)])
    assert result.exit_code == 0, result.output
    cfg = json.loads((tmp_path / ".mcp.json").read_text())
    assert cfg["mcpServers"]["iaclens"]["args"] == ["serve", "--path", str(a.resolve())]
    assert Path(tmp_path / "CLAUDE.md").exists()
