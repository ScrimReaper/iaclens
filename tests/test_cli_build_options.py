from click.testing import CliRunner

from infra_graph.cli import cli


def test_build_has_no_mode_option():
    result = CliRunner().invoke(cli, ["build", "--mode", "deep", "."])
    assert result.exit_code != 0
    assert "no such option" in result.output.lower()
