"""Shell completion: script emission and node-id suggestion callback."""

import networkx as nx
import pytest
from click.testing import CliRunner

from infra_graph.cli import cli
from infra_graph.completion import (
    SUPPORTED_SHELLS,
    complete_node_ids,
    emit_completion_script,
)
from infra_graph.graph import toon


class _Ctx:
    """Minimal stand-in for a Click context during completion."""

    def __init__(self, params):
        self.params = params


def _write_graph(root, ids):
    g = nx.DiGraph()
    for nid in ids:
        g.add_node(nid, name=nid, type="r", kind="k")
    out = root / "iaclens-out"
    out.mkdir(parents=True, exist_ok=True)
    toon.dump_graph(g, out / "graph.toon")


# ── script emission ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("shell", SUPPORTED_SHELLS)
def test_emit_returns_nonempty_script(shell):
    script = emit_completion_script(shell)
    assert script.strip()
    assert "_IACLENS_COMPLETE" in script


def test_emit_rejects_unknown_shell():
    with pytest.raises(ValueError):
        emit_completion_script("powershell")


def test_completion_command_prints_script():
    result = CliRunner().invoke(cli, ["completion", "bash"])
    assert result.exit_code == 0
    assert "_IACLENS_COMPLETE" in result.output


def test_completion_command_rejects_unknown_shell():
    result = CliRunner().invoke(cli, ["completion", "tcsh"])
    assert result.exit_code != 0


# ── node-id callback ─────────────────────────────────────────────────────────

def test_complete_node_ids_matches_substring(tmp_path):
    _write_graph(tmp_path, ["ns/wazuh/a1", "ns/wazuh/b1", "ns/other/c1"])
    ctx = _Ctx({"path": str(tmp_path)})
    got = [c.value for c in complete_node_ids(ctx, None, "wazuh")]
    assert set(got) == {"ns/wazuh/a1", "ns/wazuh/b1"}


def test_complete_node_ids_is_case_insensitive(tmp_path):
    _write_graph(tmp_path, ["ns/Wazuh/a1"])
    ctx = _Ctx({"path": str(tmp_path)})
    got = [c.value for c in complete_node_ids(ctx, None, "WAZUH")]
    assert got == ["ns/Wazuh/a1"]


def test_complete_node_ids_no_graph_returns_empty(tmp_path):
    ctx = _Ctx({"path": str(tmp_path)})
    assert complete_node_ids(ctx, None, "anything") == []


def test_complete_node_ids_never_raises_on_bad_root():
    ctx = _Ctx({"path": "/nonexistent/does/not/exist"})
    assert complete_node_ids(ctx, None, "x") == []


def test_complete_node_ids_caps_results(tmp_path):
    _write_graph(tmp_path, [f"ns/w{i:03d}" for i in range(200)])
    ctx = _Ctx({"path": str(tmp_path)})
    got = complete_node_ids(ctx, None, "ns/")
    assert len(got) <= 50


def test_complete_node_ids_reads_project_path_param(tmp_path):
    # `path` command uses the option name `project_path`, not `path`.
    _write_graph(tmp_path, ["ns/wazuh/a1"])
    ctx = _Ctx({"project_path": str(tmp_path)})
    got = [c.value for c in complete_node_ids(ctx, None, "wazuh")]
    assert got == ["ns/wazuh/a1"]
