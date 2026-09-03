from click.testing import CliRunner

from infra_graph.cli import cli


def test_version_flag_runs():
    result = CliRunner().invoke(cli, ["--version"])
    assert result.exit_code == 0, result.output
    assert "0.6" in result.output
