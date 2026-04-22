"""BFS-based blast radius / impact traversal."""

from __future__ import annotations

from collections import deque
from typing import Any

import networkx as nx


def get_blast_radius(
    graph: nx.DiGraph,
    node_id: str,
    max_depth: int = 5,
    direction: str = "downstream",
) -> dict[str, Any]:
    """
    Perform BFS from node_id to find all affected resources.

    Args:
        graph:      The infrastructure DiGraph.
        node_id:    Starting node.
        max_depth:  Maximum BFS depth.
        direction:  "downstream" (successors), "upstream" (predecessors), or "both".

    Returns:
        {
            "root": node_id,
            "affected": [
                {
                    "node_id": ...,
                    "depth": ...,
                    "type": ...,
                    "edge_chain": [...],   # list of (from, edge_type, to)
                },
                ...
            ],
            "total_affected": int,
            "max_depth_reached": int,
        }
    """
    if node_id not in graph:
        return {
            "root": node_id,
            "affected": [],
            "total_affected": 0,
            "max_depth_reached": 0,
            "error": f"Node '{node_id}' not found in graph",
        }

    visited: dict[str, int] = {}  # node_id → depth
    # edge_chains: node_id → list of (from, edge_type, to) tuples
    chains: dict[str, list] = {node_id: []}
    queue: deque = deque([(node_id, 0)])
    visited[node_id] = 0
    max_reached = 0

    def _neighbors(nid: str) -> list[tuple[str, dict]]:
        """Return (neighbor_id, edge_data) based on direction."""
        neighbors = []
        if direction in ("downstream", "both"):
            for _, succ, data in graph.out_edges(nid, data=True):
                neighbors.append((succ, data, "out"))
        if direction in ("upstream", "both"):
            for pred, _, data in graph.in_edges(nid, data=True):
                neighbors.append((pred, data, "in"))
        return neighbors

    while queue:
        current, depth = queue.popleft()
        max_reached = max(max_reached, depth)

        if depth >= max_depth:
            continue

        for neighbor, edge_data, edge_dir in _neighbors(current):
            if neighbor in visited:
                continue
            visited[neighbor] = depth + 1
            # Build edge chain
            parent_chain = chains.get(current, [])
            if edge_dir == "out":
                new_link = (current, edge_data.get("type", "unknown"), neighbor)
            else:
                new_link = (neighbor, edge_data.get("type", "unknown"), current)
            chains[neighbor] = parent_chain + [new_link]
            queue.append((neighbor, depth + 1))

    affected = []
    for nid, depth in sorted(visited.items(), key=lambda x: x[1]):
        if nid == node_id:
            continue
        node_attrs = dict(graph.nodes.get(nid, {}))
        affected.append(
            {
                "node_id": nid,
                "depth": depth,
                "type": node_attrs.get("type", "unknown"),
                "kind": node_attrs.get("kind", ""),
                "file": node_attrs.get("file"),
                "edge_chain": chains.get(nid, []),
            }
        )

    return {
        "root": node_id,
        "affected": affected,
        "total_affected": len(affected),
        "max_depth_reached": max_reached,
    }


def find_path(
    graph: nx.DiGraph, from_node: str, to_node: str
) -> dict[str, Any]:
    """Find the shortest path between two nodes."""
    if from_node not in graph:
        return {"error": f"Source node '{from_node}' not found"}
    if to_node not in graph:
        return {"error": f"Target node '{to_node}' not found"}

    try:
        path = nx.shortest_path(graph, from_node, to_node)
        edges = []
        for i in range(len(path) - 1):
            edge_data = graph.edges.get((path[i], path[i + 1]), {})
            edges.append(
                {
                    "from": path[i],
                    "to": path[i + 1],
                    "type": edge_data.get("type", "unknown"),
                    "confidence": edge_data.get("confidence", 1.0),
                }
            )
        return {
            "path": path,
            "length": len(path) - 1,
            "edges": edges,
        }
    except nx.NetworkXNoPath:
        return {"path": [], "length": -1, "error": "No path found"}
    except nx.NodeNotFound as e:
        return {"path": [], "length": -1, "error": str(e)}
