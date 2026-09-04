"""The query command presents itself as keyword search, not Q&A."""

from click.testing import CliRunner

from infra_graph.cli import cli


def test_query_help_says_keyword_search():
    result = CliRunner().invoke(cli, ["query", "--help"])
    assert result.exit_code == 0
    assert "TERMS" in result.output          # argument renamed
    assert "keyword" in result.output.lower()  # help reframed
    assert "question" not in result.output.lower()
