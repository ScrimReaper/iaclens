"""
Community detection for the infrastructure graph.

Tries graspologic Leiden first; falls back to NetworkX greedy modularity.
"""

from __future__ import annotations

import warnings
from collections import defaultdict
from typing import Any

import networkx as nx


def assign_communities(graph: nx.DiGraph) -> list[dict[str, Any]]:
    """
    Detect communities and assign community_id to each node.

    Returns a list of community summary dicts.
    """
    if graph.number_of_nodes() == 0:
        return []

    # Convert to undirected for community detection
    undirected = graph.to_undirected()

    partition: dict[str, int] = {}

    # Try graspologic Leiden
    leiden_ok = False
    try:
        from graspologic.partition import leiden
        adj = nx.to_scipy_sparse_array(undirected, nodelist=list(undirected.nodes()))
        labels, _ = leiden(adj)
        nodes_list = list(undirected.nodes())
        for i, nid in enumerate(nodes_list):
            partition[nid] = int(labels[i])
        leiden_ok = True
    except ImportError:
        pass
    except Exception as exc:
        warnings.warn(f"[community] graspologic Leiden failed: {exc}. Falling back.")

    if not leiden_ok:
        try:
            communities = nx.algorithms.community.greedy_modularity_communities(undirected)
            for cid, community in enumerate(communities):
                for nid in community:
                    partition[nid] = cid
        except Exception as exc:
            warnings.warn(f"[community] greedy_modularity_communities failed: {exc}. Assigning all to community 0.")
            for nid in graph.nodes():
                partition[nid] = 0

    # Assign community_id to nodes
    for nid in graph.nodes():
        graph.nodes[nid]["community_id"] = partition.get(nid, 0)

    # Build community summaries
    communities_map: dict[int, list[str]] = defaultdict(list)
    for nid, cid in partition.items():
        communities_map[cid].append(nid)

    summaries = []
    for cid, members in sorted(communities_map.items()):
        type_counts: dict[str, int] = defaultdict(int)
        for nid in members:
            t = graph.nodes.get(nid, {}).get("type", "unknown")
            type_counts[t] += 1

        # Representative nodes: highest degree
        by_degree = sorted(members, key=lambda n: graph.degree(n), reverse=True)

        summaries.append(
            {
                "community_id": cid,
                "size": len(members),
                "top_node_types": dict(
                    sorted(type_counts.items(), key=lambda x: x[1], reverse=True)
                ),
                "representative_nodes": by_degree[:5],
                "members": members,
            }
        )

    return summaries


def get_community_summary(graph: nx.DiGraph) -> list[dict[str, Any]]:
    """Return community summaries without re-assigning (reads community_id from nodes)."""
    communities_map: dict[int, list[str]] = defaultdict(list)
    for nid, attrs in graph.nodes(data=True):
        cid = attrs.get("community_id", 0)
        communities_map[cid].append(nid)

    summaries = []
    for cid, members in sorted(communities_map.items()):
        type_counts: dict[str, int] = defaultdict(int)
        for nid in members:
            t = graph.nodes.get(nid, {}).get("type", "unknown")
            type_counts[t] += 1

        by_degree = sorted(members, key=lambda n: graph.degree(n), reverse=True)

        summaries.append(
            {
                "community_id": cid,
                "size": len(members),
                "top_node_types": dict(
                    sorted(type_counts.items(), key=lambda x: x[1], reverse=True)
                ),
                "representative_nodes": by_degree[:5],
                "members": members,
            }
        )

    return summaries


def find_cross_community_edges(graph: nx.DiGraph) -> list[dict[str, Any]]:
    """
    Return edges that cross community boundaries.
    Sorted by 'unexpectedness' (higher when communities are far apart in size).
    """
    cross_edges = []
    for frm, to, data in graph.edges(data=True):
        cid_from = graph.nodes.get(frm, {}).get("community_id", -1)
        cid_to = graph.nodes.get(to, {}).get("community_id", -1)
        if cid_from != cid_to and cid_from != -1 and cid_to != -1:
            cross_edges.append(
                {
                    "from": frm,
                    "to": to,
                    "from_community": cid_from,
                    "to_community": cid_to,
                    "edge_type": data.get("type", "unknown"),
                    "confidence": data.get("confidence", 1.0),
                }
            )

    # Rank by unexpectedness: prefer INFERRED/AMBIGUOUS and lower confidence
    def _score(e: dict) -> float:
        prov = graph.edges.get((e["from"], e["to"]), {}).get("provenance", "EXTRACTED")
        prov_score = {"EXTRACTED": 0, "INFERRED": 1, "AMBIGUOUS": 2}.get(prov, 0)
        return prov_score + (1.0 - e["confidence"])

    cross_edges.sort(key=_score, reverse=True)
    return cross_edges
