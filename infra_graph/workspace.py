"""Several repo roots served as ONE federated graph.

`iaclens serve --path A --path B` builds each root with its own GraphBuilder
(so every repo keeps its per-repo `iaclens-out/graph.toon` for the CLI), then
federates the in-memory graphs and publishes the result. A change under one
root rebuilds only that root and re-federates, so a federated graph stays
fresh without an external rebuild-all + re-federate script.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

import networkx as nx

from .graph.builder import GraphBuilder
from .graph.federation import federate_graphs
from .graph.toon import dump_graph, write_text_atomic


class Workspace:
    """Owns one GraphBuilder per root and the current federated graph."""

    def __init__(self, roots: Sequence[Path], out_file: Path | None = None) -> None:
        if not roots:
            raise ValueError("Workspace needs at least one root")
        self.roots: list[Path] = [Path(r).resolve() for r in roots]
        self.out_file: Path | None = Path(out_file).resolve() if out_file else None
        self._builders: dict[Path, GraphBuilder] = {r: GraphBuilder(r) for r in self.roots}
        self._graph: nx.DiGraph = nx.DiGraph()
        self._meta: dict[str, Any] = {}
        self._dirty: set[Path] = set()
        self._lock = threading.Lock()

    # ── Graph access ─────────────────────────────────────────────────────────

    def get(self) -> nx.DiGraph:
        """The current federated graph. Rebuilds publish a NEW object, so a
        caller holding this reference keeps a consistent snapshot."""
        return self._graph

    @property
    def meta(self) -> dict[str, Any]:
        return self._meta

    # ── Building ─────────────────────────────────────────────────────────────

    def build_all(self) -> dict[str, Any]:
        return self.rebuild(self.roots)

    def rebuild(self, roots: Iterable[Path]) -> dict[str, Any]:
        """Rebuild the given roots, re-federate ALL roots, publish."""
        rebuilt = [Path(r).resolve() for r in roots]
        for root in rebuilt:
            self._builders[root].build()
        merged, meta = federate_graphs([b.graph for b in self._builders.values()])
        if self.out_file is not None:
            self._write_out(merged, meta)
        self._graph, self._meta = merged, meta
        return {
            "roots_rebuilt": [str(r) for r in rebuilt],
            "nodes": merged.number_of_nodes(),
            "edges": merged.number_of_edges(),
            **meta,
        }

    def _write_out(self, graph: nx.DiGraph, meta: dict[str, Any]) -> None:
        assert self.out_file is not None
        self.out_file.parent.mkdir(parents=True, exist_ok=True)
        if self.out_file.suffix == ".json":
            nodes = [{"id": nid, **attrs} for nid, attrs in graph.nodes(data=True)]
            edges = [{"from": f, "to": t, **d} for f, t, d in graph.edges(data=True)]
            payload = json.dumps(
                {"meta": meta, "nodes": nodes, "edges": edges}, indent=2, default=str
            )
            write_text_atomic(self.out_file, payload)
        else:
            dump_graph(graph, self.out_file, meta)

    # ── Change tracking (fed by the file watcher) ────────────────────────────

    def root_for(self, path: Path | str) -> Path | None:
        """The served root that contains `path`, or None."""
        p = Path(path)
        if not p.is_absolute():
            p = p.resolve()
        for root in sorted(self.roots, key=lambda r: len(r.parts), reverse=True):
            if p == root or root in p.parents:
                return root
        return None

    def mark_dirty(self, path: Path | str) -> None:
        root = self.root_for(path)
        if root is None:
            return
        with self._lock:
            self._dirty.add(root)

    def flush_dirty(self) -> dict[str, Any]:
        """Rebuild every root marked dirty since the last flush. No-op when
        nothing is dirty."""
        with self._lock:
            roots = sorted(self._dirty)
            self._dirty.clear()
        if not roots:
            return {}
        return self.rebuild(roots)

    def rebuild_path(self, path: Path | str) -> dict[str, Any] | None:
        """Rebuild the served root that `path` belongs to; None if `path` is
        not under any served root."""
        root = self.root_for(path)
        if root is None:
            return None
        return self.rebuild([root])
