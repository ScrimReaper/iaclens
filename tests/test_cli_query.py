"""The query command presents itself as keyword search, not Q&A."""

from click.testing import CliRunner

from infra_graph.cli import cli


def test_query_help_says_keyword_search():
    result = CliRunner().invoke(cli, ["query", "--help"])
    assert result.exit_code == 0
    assert "TERMS" in result.output          # argument renamed
    assert "keyword" in result.output.lower()  # help reframed
    assert "question" not in result.output.lower()


def test_blank_query_reports_no_matches(tmp_path):
    from infra_graph.graph.builder import GraphBuilder

    (tmp_path / "conf.yml").write_text("a: 1\n")
    GraphBuilder(tmp_path).build()
    result = CliRunner().invoke(cli, ["query", "   ", "--path", str(tmp_path)])
    assert result.exit_code == 0
    assert "No matching resources found." in result.output
