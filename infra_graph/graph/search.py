"""Tokenized keyword search shared by the CLI and the MCP server.

Splits the query into terms and scores each node by the sum of the field
weights each term matches. Any-term match, highest score first. This keeps
multi-word input useful instead of matching the whole phrase as one literal
substring (which scored zero on every node).
"""

from __future__ import annotations

import networkx as nx

# field name -> weight. Order is the stable order of matched_fields.
_FIELDS: tuple[tuple[str, int], ...] = (
    ("id", 3),
    ("name", 2),
    ("type", 1),
    ("kind", 1),
    ("labels", 1),
)


def _field_value(nid: str, attrs: dict, field: str) -> str:
    if field == "id":
        return nid.lower()
    if field == "labels":
        labels = attrs.get("labels") or {}
        return " ".join(f"{k}={v}" for k, v in labels.items()).lower()
    return str(attrs.get(field, "")).lower()


def _tokens(query: str) -> list[str]:
    return [t for t in query.lower().split() if len(t) >= 2]


def search_nodes(graph: nx.DiGraph, query: str) -> list[dict]:
    terms = _tokens(query)
    if not terms:
        return []

    results: list[dict] = []
    for nid, attrs in graph.nodes(data=True):
        values = {field: _field_value(nid, attrs, field) for field, _ in _FIELDS}
        score = 0
        matched: list[str] = []
        for field, weight in _FIELDS:
            value = values[field]
            if any(term in value for term in terms):
                score += weight * sum(1 for term in terms if term in value)
                matched.append(field)
        if score > 0:
            results.append(
                {"id": nid, "score": score, "matched_fields": matched, "attrs": attrs}
            )

    results.sort(key=lambda r: r["score"], reverse=True)
    return results
