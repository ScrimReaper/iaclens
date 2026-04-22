"""Generate GRAPH_REPORT.md for the infrastructure knowledge graph."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import networkx as nx

from .community import find_cross_community_edges, get_community_summary

_REPORT_FILE = "GRAPH_REPORT.md"


def _top_nodes_by_degree(graph: nx.DiGraph, n: int = 5) -> list[dict]:
    degrees = [(nid, graph.degree(nid)) for nid in graph.nodes()]
    degrees.sort(key=lambda x: x[1], reverse=True)
    results = []
    for nid, deg in degrees[:n]:
        attrs = dict(graph.nodes[nid])
        results.append(
            {
                "id": nid,
                "degree": deg,
                "type": attrs.get("type", ""),
                "kind": attrs.get("kind", ""),
                "file": attrs.get("file", ""),
            }
        )
    return results


def generate_report(graph: nx.DiGraph, out_dir: Path, stats: dict[str, Any] | None = None) -> Path:
    """
    Generate GRAPH_REPORT.md in out_dir.

    Returns the path to the generated file.
    """
    report_path = out_dir / _REPORT_FILE
    stats = stats or {}

    communities = get_community_summary(graph)
    cross_edges = find_cross_community_edges(graph)
    hub_nodes = _top_nodes_by_degree(graph, n=5)

    # Estimate token savings
    total_files = stats.get("files_parsed", 0) + stats.get("files_skipped", 0)
    naive_tokens = total_files * 500  # rough estimate
    graph_tokens = graph.number_of_nodes() * 20 + graph.number_of_edges() * 10

    lines: list[str] = []

    lines.append("# infra-graph: Graph Report")
    lines.append(f"\n_Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}_\n")

    # ── Stats ────────────────────────────────────────────────────────────────
    lines.append("## Graph Statistics\n")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Total nodes | {graph.number_of_nodes()} |")
    lines.append(f"| Total edges | {graph.number_of_edges()} |")
    lines.append(f"| Files parsed | {stats.get('files_parsed', '?')} |")
    lines.append(f"| Files skipped (cached) | {stats.get('files_skipped', 0)} |")
    lines.append(f"| Communities detected | {len(communities)} |")
    lines.append("")

    # ── God nodes ────────────────────────────────────────────────────────────
    lines.append("## God Nodes (Top 5 by Degree)\n")
    lines.append("| Node ID | Type | Kind | Degree | File |")
    lines.append("|---------|------|------|--------|------|")
    for n in hub_nodes:
        file_str = Path(n["file"]).name if n["file"] else "—"
        lines.append(f"| `{n['id']}` | {n['type']} | {n['kind']} | {n['degree']} | {file_str} |")
    lines.append("")

    # ── Community map ─────────────────────────────────────────────────────────
    lines.append("## Community Map\n")
    lines.append("| Community | Size | Top Types | Representative Nodes |")
    lines.append("|-----------|------|-----------|----------------------|")
    for c in communities:
        top_types = ", ".join(f"{t}({n})" for t, n in list(c["top_node_types"].items())[:3])
        rep_nodes = ", ".join(f"`{n}`" for n in c["representative_nodes"][:3])
        lines.append(
            f"| {c['community_id']} | {c['size']} | {top_types} | {rep_nodes} |"
        )
    lines.append("")

    # ── Cross-community edges ─────────────────────────────────────────────────
    lines.append("## Surprising Cross-Community Edges\n")
    if cross_edges:
        lines.append("| From | To | Edge Type | Confidence | Communities |")
        lines.append("|------|----|-----------|------------|-------------|")
        for e in cross_edges[:10]:
            lines.append(
                f"| `{e['from']}` | `{e['to']}` | {e['edge_type']} "
                f"| {e['confidence']:.1f} | {e['from_community']}→{e['to_community']} |"
            )
    else:
        lines.append("_No cross-community edges detected._")
    lines.append("")

    # ── Suggested questions ───────────────────────────────────────────────────
    lines.append("## Suggested Questions\n")
    questions = _generate_questions(graph, hub_nodes, communities)
    for q in questions:
        lines.append(f"- {q}")
    lines.append("")

    # ── Token benchmark ───────────────────────────────────────────────────────
    lines.append("## Token Benchmark\n")
    lines.append("| Approach | Estimated Tokens |")
    lines.append("|----------|-----------------|")
    lines.append(f"| Naive (read all files) | ~{naive_tokens:,} |")
    lines.append(f"| Graph context | ~{graph_tokens:,} |")
    if naive_tokens > 0:
        savings_pct = max(0, (1 - graph_tokens / naive_tokens) * 100)
        lines.append(f"| **Savings** | **~{savings_pct:.0f}%** |")
    lines.append("")
    lines.append(
        "> Estimates based on ~500 tokens/file (naive) vs. "
        "~20 tokens/node + ~10 tokens/edge (graph)."
    )

    report_path.write_text("\n".join(lines) + "\n")
    return report_path


def _generate_questions(
    graph: nx.DiGraph,
    hub_nodes: list[dict],
    communities: list[dict],
) -> list[str]:
    questions = []

    if hub_nodes:
        top = hub_nodes[0]
        questions.append(
            f"What is the blast radius if `{top['id']}` changes or is removed?"
        )

    if len(communities) > 1:
        c0 = communities[0]
        rep = c0["representative_nodes"][0] if c0["representative_nodes"] else "?"
        questions.append(
            f"Which resources in community {c0['community_id']} depend on `{rep}`?"
        )

    # Find any AMBIGUOUS edges
    ambiguous = [
        (f, t) for f, t, d in graph.edges(data=True)
        if d.get("provenance") == "AMBIGUOUS"
    ]
    if ambiguous:
        f, t = ambiguous[0]
        questions.append(
            f"The edge `{f}` → `{t}` is dynamic — what is the actual runtime value?"
        )

    questions.append("Which resources are orphaned (no inbound or outbound edges)?")
    questions.append(
        "Are there any secrets or variables referenced by resources not in this repo?"
    )

    return questions[:5]
