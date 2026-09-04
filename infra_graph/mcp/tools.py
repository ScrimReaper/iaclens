"""
10 MCP tool implementations for the iaclens plugin.
"""

from __future__ import annotations

import re
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

import networkx as nx

from ..graph.blast_radius import get_blast_radius as _bfs_blast
from ..graph.builder import GraphBuilder
from ..graph.community import find_cross_community_edges, get_community_summary

# ── Tool 1: get_minimal_context ──────────────────────────────────────────────

def get_minimal_context(graph: nx.DiGraph) -> dict[str, Any]:
    """
    ~100-token summary: god nodes and top communities.
    """
    if graph.number_of_nodes() == 0:
        return {"summary": "Graph is empty. Run `iaclens build <path>` first."}

    # Top 3 hub nodes
    by_degree = sorted(graph.nodes(), key=lambda n: graph.degree(n), reverse=True)
    god_nodes = []
    for nid in by_degree[:3]:
        attrs = graph.nodes[nid]
        god_nodes.append(
            {
                "id": nid,
                "type": attrs.get("type", "?"),
                "degree": graph.degree(nid),
                "community": attrs.get("community_id", 0),
            }
        )

    communities = get_community_summary(graph)
    top_communities = [
        {
            "id": c["community_id"],
            "size": c["size"],
            "types": list(c["top_node_types"].keys())[:3],
            "rep": c["representative_nodes"][:2],
        }
        for c in communities[:3]
    ]

    return {
        "nodes": graph.number_of_nodes(),
        "edges": graph.number_of_edges(),
        "communities": len(communities),
        "god_nodes": god_nodes,
        "top_communities": top_communities,
        "hint": "Use get_blast_radius or query_graph to explore further.",
    }


# ── Tool 2: get_blast_radius ─────────────────────────────────────────────────

def get_blast_radius(
    graph: nx.DiGraph,
    node_id: str,
    max_depth: int = 5,
) -> dict[str, Any]:
    """
    BFS traversal from node_id; returns all affected resources with depth and edge chain.
    """
    return _bfs_blast(graph, node_id, max_depth=max_depth)


# ── Tool 3: query_graph ──────────────────────────────────────────────────────

def query_graph(
    graph: nx.DiGraph,
    from_node: str,
    direction: str = "downstream",
    edge_types: list[str] | None = None,
    max_depth: int = 3,
    token_budget: int = 2000,
) -> dict[str, Any]:
    """
    BFS/DFS from any node, optionally filtered by edge types.
    """
    if from_node not in graph:
        # Try fuzzy match
        matches = [n for n in graph.nodes() if from_node.lower() in n.lower()]
        if matches:
            return {
                "error": f"Node '{from_node}' not found.",
                "suggestions": matches[:5],
            }
        return {"error": f"Node '{from_node}' not found in graph."}

    visited: dict[str, int] = {}
    queue: deque = deque([(from_node, 0)])
    visited[from_node] = 0
    result_edges: list[dict] = []
    result_nodes: list[dict] = []
    token_count = 0

    while queue:
        current, depth = queue.popleft()
        if depth >= max_depth:
            continue

        # Get edges based on direction
        if direction in ("downstream", "both"):
            candidate_edges = [(current, t, d) for _, t, d in graph.out_edges(current, data=True)]
        else:
            candidate_edges = []
        if direction in ("upstream", "both"):
            candidate_edges += [(s, current, d) for s, _, d in graph.in_edges(current, data=True)]

        for frm, to, data in candidate_edges:
            # Filter by edge types if specified
            if edge_types and data.get("type") not in edge_types:
                continue

            neighbor = to if frm == current else frm

            edge_entry = {
                "from": frm,
                "to": to,
                "type": data.get("type", ""),
                "confidence": data.get("confidence", 1.0),
                "provenance": data.get("provenance", ""),
            }
            result_edges.append(edge_entry)
            token_count += 10

            if neighbor not in visited:
                visited[neighbor] = depth + 1
                n_attrs = dict(graph.nodes.get(neighbor, {}))
                result_nodes.append(
                    {
                        "id": neighbor,
                        "type": n_attrs.get("type", ""),
                        "kind": n_attrs.get("kind", ""),
                        "file": n_attrs.get("file"),
                        "depth": depth + 1,
                    }
                )
                token_count += 20
                if token_count < token_budget:
                    queue.append((neighbor, depth + 1))

    return {
        "root": from_node,
        "direction": direction,
        "nodes": result_nodes,
        "edges": result_edges,
        "total_nodes": len(result_nodes),
        "total_edges": len(result_edges),
        "truncated": token_count >= token_budget,
    }


# ── Tool 4: get_resource_context ────────────────────────────────────────────

def get_resource_context(graph: nx.DiGraph, node_id: str) -> dict[str, Any]:
    """
    Full context for one resource: edges, community, source file, line number.
    """
    if node_id not in graph:
        matches = [n for n in graph.nodes() if node_id.lower() in n.lower()]
        return {
            "error": f"Node '{node_id}' not found.",
            "suggestions": matches[:5],
        }

    attrs = dict(graph.nodes[node_id])

    out_edges = []
    for _, target, data in graph.out_edges(node_id, data=True):
        out_edges.append(
            {
                "to": target,
                "type": data.get("type", ""),
                "confidence": data.get("confidence", 1.0),
                "provenance": data.get("provenance", ""),
            }
        )

    in_edges = []
    for source, _, data in graph.in_edges(node_id, data=True):
        in_edges.append(
            {
                "from": source,
                "type": data.get("type", ""),
                "confidence": data.get("confidence", 1.0),
                "provenance": data.get("provenance", ""),
            }
        )

    # Community members
    comm_id = attrs.get("community_id", 0)
    community_members = [
        n for n, a in graph.nodes(data=True)
        if a.get("community_id") == comm_id and n != node_id
    ]

    return {
        "id": node_id,
        "type": attrs.get("type", ""),
        "kind": attrs.get("kind", ""),
        "name": attrs.get("name", ""),
        "file": attrs.get("file"),
        "line": attrs.get("line"),
        "labels": attrs.get("labels", {}),
        "community_id": comm_id,
        "community_size": len(community_members) + 1,
        "out_edges": out_edges,
        "in_edges": in_edges,
        "degree": graph.degree(node_id),
    }


# ── Tool 5: get_architecture_overview ────────────────────────────────────────

def get_architecture_overview(graph: nx.DiGraph) -> dict[str, Any]:
    """
    Community-level map with coupling warnings.
    """
    communities = get_community_summary(graph)
    cross_edges = find_cross_community_edges(graph)

    # Coupling warnings: communities with many cross-edges
    cross_counts: dict[tuple, int] = defaultdict(int)
    for e in cross_edges:
        key = tuple(sorted([e["from_community"], e["to_community"]]))
        cross_counts[key] += 1

    warnings_list = []
    for (c1, c2), count in sorted(cross_counts.items(), key=lambda x: x[1], reverse=True)[:5]:
        if count >= 2:
            warnings_list.append(
                f"Communities {c1} and {c2} have {count} cross-community edges — potential tight coupling."
            )

    # Node type distribution
    type_dist: dict[str, int] = defaultdict(int)
    for _, attrs in graph.nodes(data=True):
        type_dist[attrs.get("type", "unknown")] += 1

    return {
        "total_nodes": graph.number_of_nodes(),
        "total_edges": graph.number_of_edges(),
        "node_types": dict(sorted(type_dist.items(), key=lambda x: x[1], reverse=True)),
        "communities": [
            {
                "id": c["community_id"],
                "size": c["size"],
                "top_types": c["top_node_types"],
                "rep_nodes": c["representative_nodes"][:3],
            }
            for c in communities
        ],
        "cross_community_edges": len(cross_edges),
        "coupling_warnings": warnings_list,
    }


# ── Tool 6: detect_changes ────────────────────────────────────────────────────

def detect_changes(graph: nx.DiGraph, diff_text: str) -> dict[str, Any]:
    """
    Risk-scored impact analysis for a git diff.

    Parses unified diff, finds modified filenames, maps to graph nodes,
    computes blast radius for each.
    """
    # Extract filenames from unified diff header lines
    modified_files: set[str] = set()
    for line in diff_text.splitlines():
        # +++ b/path/to/file or --- a/path/to/file
        m = re.match(r"^(?:\+\+\+|---)\s+[ab]/(.+)$", line)
        if m:
            modified_files.add(m.group(1).strip())

    if not modified_files:
        return {
            "modified_files": [],
            "affected_resources": [],
            "risk_score": 0,
            "message": "No modified files detected in diff.",
        }

    # Map files to nodes
    file_to_nodes: dict[str, list[str]] = defaultdict(list)
    for nid, attrs in graph.nodes(data=True):
        node_file = attrs.get("file") or ""
        if not node_file:
            continue
        # Normalize: compare by suffix
        for modified_file in modified_files:
            if node_file.endswith(modified_file) or modified_file.endswith(Path(node_file).name):
                file_to_nodes[modified_file].append(nid)

    all_affected: dict[str, dict] = {}
    per_file_results: list[dict] = []

    for modified_file in sorted(modified_files):
        direct_nodes = file_to_nodes.get(modified_file, [])
        affected_set: dict[str, int] = {}  # node_id → max_depth

        for root_node in direct_nodes:
            blast = _bfs_blast(graph, root_node, max_depth=5)
            for item in blast.get("affected", []):
                nid = item["node_id"]
                depth = item["depth"]
                if nid not in affected_set or affected_set[nid] > depth:
                    affected_set[nid] = depth

        all_affected.update(affected_set)

        # Risk score for this file: based on direct nodes' degree + blast radius
        file_risk = 0
        for nid in direct_nodes:
            file_risk += graph.degree(nid) * 10
        file_risk += len(affected_set) * 5

        per_file_results.append(
            {
                "file": modified_file,
                "direct_nodes": direct_nodes,
                "blast_radius": len(affected_set),
                "risk_score": file_risk,
            }
        )

    # Overall risk
    total_risk = sum(r["risk_score"] for r in per_file_results)
    risk_level = "low"
    if total_risk > 200:
        risk_level = "high"
    elif total_risk > 50:
        risk_level = "medium"

    per_file_results.sort(key=lambda x: x["risk_score"], reverse=True)

    return {
        "modified_files": list(modified_files),
        "per_file": per_file_results,
        "total_affected_nodes": len(all_affected),
        "risk_score": total_risk,
        "risk_level": risk_level,
        "most_affected_nodes": [
            {"node_id": nid, "depth": d}
            for nid, d in sorted(all_affected.items(), key=lambda x: x[1])[:10]
        ],
    }


# ── Tool 7: find_hub_nodes ────────────────────────────────────────────────────

def find_hub_nodes(graph: nx.DiGraph, top_n: int = 10) -> dict[str, Any]:
    """
    Return the highest-degree resources (god nodes).
    """
    degrees = [(nid, graph.degree(nid)) for nid in graph.nodes()]
    degrees.sort(key=lambda x: x[1], reverse=True)

    hubs = []
    for nid, deg in degrees[:top_n]:
        attrs = dict(graph.nodes[nid])
        in_deg = graph.in_degree(nid)
        out_deg = graph.out_degree(nid)
        hubs.append(
            {
                "id": nid,
                "type": attrs.get("type", ""),
                "kind": attrs.get("kind", ""),
                "file": attrs.get("file"),
                "degree": deg,
                "in_degree": in_deg,
                "out_degree": out_deg,
                "community_id": attrs.get("community_id", 0),
            }
        )

    return {"hub_nodes": hubs, "total_nodes": graph.number_of_nodes()}


# ── Tool 8: get_knowledge_gaps ────────────────────────────────────────────────

def get_knowledge_gaps(graph: nx.DiGraph) -> dict[str, Any]:
    """
    Find orphaned resources and AMBIGUOUS edges.
    """
    orphans = []
    for nid in graph.nodes():
        if graph.degree(nid) == 0:
            attrs = dict(graph.nodes[nid])
            orphans.append(
                {
                    "id": nid,
                    "type": attrs.get("type", ""),
                    "file": attrs.get("file"),
                }
            )

    ambiguous_edges = []
    for frm, to, data in graph.edges(data=True):
        if data.get("provenance") == "AMBIGUOUS":
            ambiguous_edges.append(
                {
                    "from": frm,
                    "to": to,
                    "type": data.get("type", ""),
                    "confidence": data.get("confidence", 0.5),
                }
            )

    # Dangling references: edges pointing to nodes that don't exist as real nodes
    # (unknown type nodes)
    dangling = []
    for nid, attrs in graph.nodes(data=True):
        if attrs.get("type") == "unknown":
            dangling.append(
                {
                    "id": nid,
                    "referenced_by": [
                        s for s, _, _ in graph.in_edges(nid, data=True)
                    ],
                }
            )

    return {
        "orphaned_resources": orphans,
        "orphan_count": len(orphans),
        "ambiguous_edges": ambiguous_edges,
        "ambiguous_count": len(ambiguous_edges),
        "dangling_references": dangling[:20],
        "dangling_count": len(dangling),
        "total_gaps": len(orphans) + len(ambiguous_edges) + len(dangling),
    }


# ── Tool 9: build_or_update_graph ────────────────────────────────────────────

def build_or_update_graph(
    path: str,
    update_only: bool = False,
) -> dict[str, Any]:
    """
    Trigger a graph rebuild from within the assistant.
    """
    project_path = Path(path).resolve()
    if not project_path.exists():
        return {"error": f"Path '{path}' does not exist."}
    if not project_path.is_dir():
        return {"error": f"Path '{path}' is not a directory."}

    builder = GraphBuilder(project_path)
    try:
        stats = builder.build(update_only=update_only)
        return {
            "success": True,
            "path": str(project_path),
            "stats": stats,
            "graph_file": str(builder.out_dir / "graph.json"),
            "update_only": update_only,
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}


# ── Tool 10: search_resources ─────────────────────────────────────────────────

def search_resources(graph: nx.DiGraph, query: str) -> dict[str, Any]:
    """
    Keyword search across node names, types, labels.

    Matches any term; nodes matching more terms rank higher.
    """
    from infra_graph.graph.search import search_nodes

    results = []
    for r in search_nodes(graph, query):
        attrs = r["attrs"]
        results.append(
            {
                "id": r["id"],
                "score": r["score"],
                "matched_fields": r["matched_fields"],
                "type": attrs.get("type", ""),
                "kind": attrs.get("kind", ""),
                "file": attrs.get("file"),
                "degree": graph.degree(r["id"]),
            }
        )

    return {
        "query": query,
        "results": results[:20],
        "total_matches": len(results),
    }
