"""Tests for the shared tokenized keyword search helper.

Fixture ids/names are chosen so each query term is a substring of exactly the
fields we intend, with no accidental collisions (no term is a substring of a
type/kind/label value here).
"""

import networkx as nx

from infra_graph.graph.search import search_nodes
from infra_graph.mcp import tools as T

# A: "wazuh" only in id, "secret" only in name -> matches both terms, distinct fields
# B: "wazuh" only in id
# C: "secret" only in name
# D: neither
_A = "ns/wazuh/a1"
_B = "ns/wazuh/b1"
_C = "ns/c1"
_D = "ns/d1"


def _graph() -> nx.DiGraph:
    g = nx.DiGraph()
    g.add_node(_A, name="alpha-secret", type="r1", kind="k1", labels={})
    g.add_node(_B, name="beta", type="r1", kind="k1", labels={})
    g.add_node(_C, name="gamma-secret", type="r1", kind="k1", labels={})
    g.add_node(_D, name="frontend", type="r2", kind="k1", labels={})
    return g


def test_multi_term_ranks_both_match_first():
    results = search_nodes(_graph(), "wazuh secret")
    # A scores id(+3, wazuh) + name(+2, secret) = 5; B=3; C=2; D excluded
    assert results[0]["id"] == _A
    assert results[0]["score"] == 5


def test_multi_word_with_filler_still_returns_real_matches():
    # filler words (find, the) match no field and add nothing; real terms still hit
    results = search_nodes(_graph(), "find the wazuh secret")
    ids = {r["id"] for r in results}
    assert ids == {_A, _B, _C}
    assert results[0]["id"] == _A


def test_single_term_matches_substring_like_before():
    results = search_nodes(_graph(), "wazuh")
    assert {r["id"] for r in results} == {_A, _B}


def test_matched_fields_reported():
    top = search_nodes(_graph(), "wazuh secret")[0]
    assert set(top["matched_fields"]) == {"id", "name"}


def test_short_and_empty_tokens_dropped():
    assert search_nodes(_graph(), "a") == []
    assert search_nodes(_graph(), "   ") == []


def test_search_resources_shape_preserved():
    out = T.search_resources(_graph(), "wazuh secret")
    assert set(out) == {"query", "results", "total_matches"}
    top = out["results"][0]
    assert set(top) >= {"id", "score", "matched_fields", "type", "kind", "file", "degree"}
    assert top["id"] == _A
