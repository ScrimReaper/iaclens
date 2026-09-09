"""
YAML dispatcher: detects file type and routes to the correct sub-parser.

Handles: Kubernetes manifests, GitHub Actions workflows, Docker Compose,
Helm charts, Kustomize overlays, Helm templates (Go {{}} directives stripped),
Ansible playbooks and task files, and any other YAML file (generic fallback).
"""

from __future__ import annotations

import re
import warnings
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from ._ids import qualified, rel_posix
from .actions_schema import ActionsParser
from .ansible_schema import AnsibleParser
from .compose_schema import ComposeParser
from .helm_schema import HelmParser
from .k8s_schema import KubernetesParser, is_kubernetes_file

_yaml = YAML()
_yaml.preserve_quotes = True

# Detects whether a file contains any Helm/Go template directives
_HELM_DIRECTIVE_RE = re.compile(r"\{\{")


def _strip_helm_directives(text: str) -> str:
    """
    Strip Go/Helm template directives so the static YAML structure is parseable.

    Strategy (line-by-line, no cross-line regex):
    - A line whose ENTIRE non-whitespace content is `{{...}}` expressions is
      dropped (e.g. ``{{- if .Values.azure.enabled }}``,
      ``{{- toYaml .Values.foo | nindent 4 }}``).
    - Lines that contain a mix of real YAML and inline expressions have the
      ``{{...}}`` replaced with the safe YAML string ``__helm__``
      (e.g. ``name: {{ .Values.name | quote }}`` → ``name: __helm__``).

    Greedy per-line replacement handles Helm's nested-brace patterns like
    ``'{{ printf "{{.name}}" }}'`` correctly — the outermost {{ to }} pair
    is replaced as a unit.
    """
    lines: list[str] = []
    for line in text.splitlines():
        without = re.sub(r"\{\{.*\}\}", "", line)
        if without.strip() == "":
            continue
        cleaned = re.sub(r"\{\{.*\}\}", "__helm__", line)
        lines.append(cleaned)
    return "\n".join(lines)


class YAMLParser:
    """Dispatching parser for all YAML-based infrastructure files."""

    def __init__(self, project_root: Path) -> None:
        self._root = project_root.resolve()
        self._k8s = KubernetesParser()
        self._actions = ActionsParser()
        self._compose = ComposeParser()
        self._helm = HelmParser(self._root)
        self._ansible = AnsibleParser(self._root)

    @property
    def k8s_parser(self) -> KubernetesParser:
        return self._k8s

    def parse_file(self, path: Path) -> dict[str, Any]:
        """
        Auto-detect file type and parse.
        Returns {"nodes": [...], "edges": [...]}.

        Dispatch order (first match wins):
        1. Helm / Kustomize  — by filename
        2. GitHub Actions    — by path pattern
        3. Docker Compose    — by filename
        4. Ansible vars/meta — by path
        5. Ansible           — by content sniff (playbook list or task file)
        6. Kubernetes / CRD  — any YAML with apiVersion + kind + metadata
        7. Generic fallback  — any other parseable YAML dict → config node

        Steps 5–7 share ONE parse of the raw text. A file with Go-template
        directives that is not Ansible is stripped and parsed a second time
        (Helm templates): the raw parse may succeed yet yield garbage keys
        (`{{ .Release.Namespace }}` reads as a flow mapping), so it is never
        trusted for k8s. The raw parse is still made first because Ansible's
        Jinja `{{ var }}` strings are valid YAML and must reach the Ansible
        sniff intact.
        """
        empty: dict[str, Any] = {"nodes": [], "edges": []}

        # ── Helm / Kustomize (by filename, no YAML sniff needed) ─────────────
        helm_result = self._helm.parse_file(path)
        if helm_result is not None:
            return helm_result

        # ── GitHub Actions (by path pattern) ─────────────────────────────────
        if self._actions.is_actions_file(path):
            return self._actions.parse_file(path)

        # ── Docker Compose (by filename) ──────────────────────────────────────
        if self._compose.is_compose_file(path):
            return self._compose.parse_file(path)

        if path.suffix not in (".yml", ".yaml"):
            return empty

        # ── Ansible vars/meta (path-only, no parse needed) ────────────────────
        if self._ansible.is_ansible_path(path):
            return self._ansible.parse_file(path)

        try:
            text = path.read_text(encoding="utf-8")
        except Exception as exc:
            warnings.warn(f"[yaml_parser] Cannot read {path}: {exc}")
            return empty

        is_helm_template = bool(_HELM_DIRECTIVE_RE.search(text))
        raw_docs: list | None
        try:
            raw_docs = list(_yaml.load_all(text))
        except Exception as exc:
            raw_docs = None
            if not is_helm_template:
                warnings.warn(f"[yaml_parser] Cannot parse YAML in {path}: {exc}")
                return empty

        # ── Ansible (content sniff — before K8s so playbooks aren't mis-routed)
        if raw_docs is not None:
            # A single-document file is what the Ansible sniff expects.
            single_doc = raw_docs[0] if len(raw_docs) == 1 else None
            if self._ansible.is_ansible_file(path, doc=single_doc):
                return self._ansible.parse_file(path, doc=single_doc)

        stripped_text: str | None = None
        if is_helm_template:
            stripped_text = _strip_helm_directives(text)
            try:
                docs = list(_yaml.load_all(stripped_text))
            except Exception:
                return empty
        else:
            docs = raw_docs or []

        # ── Kubernetes / CRD (any apiVersion + kind + metadata) ──────────────
        k8s_docs = [d for d in docs if isinstance(d, dict) and is_kubernetes_file(d)]
        if k8s_docs:
            return self._k8s.parse_file(path, preprocessed_text=stripped_text, docs=docs)

        # ── Generic YAML fallback — any parseable YAML dict → config node ─────
        for doc in docs:
            if isinstance(doc, dict) and doc:
                config_id = qualified("config", rel_posix(path, self._root), path.stem)
                return {
                    "nodes": [{
                        "id": config_id,
                        "type": "config",
                        "kind": "generic_yaml",
                        "name": path.stem,
                        "file": str(path),
                        "line": None,
                        "labels": {},
                        "community_id": None,
                    }],
                    "edges": [],
                }

        return empty

    def finalize(self) -> list[dict]:
        """
        Call after all files are parsed. Aggregates every sub-parser's
        cross-file resolution edges (k8s selectors, kustomize resource
        linkage, plus any sub-parser exposing a callable `finalize()`).
        """
        extra_edges = self._k8s.resolve_selectors()
        extra_edges += self._k8s.resolve_cluster_selectors()
        extra_edges += self._resolve_kustomize_resources()
        for parser in (self._ansible, self._compose, self._helm, self._actions):
            fn = getattr(parser, "finalize", None)
            if callable(fn):
                extra_edges += fn()
        return extra_edges

    def _resolve_kustomize_resources(self) -> list[dict]:
        """
        Link HelmParser's pending kustomize `resources:`/`bases:` refs to the
        real nodes they point at. Cross-parser by nature (needs both
        HelmParser's pending refs and KubernetesParser's file->node map), so
        it lives here rather than in either sub-parser. Edges-only and
        idempotent: drains `_kustomize_pending` on every call.
        """
        edges: list[dict] = []
        file_nodes = self._k8s.file_nodes()
        pending = self._helm._kustomize_pending
        for overlay_id, _overlay_dir, _ref, resolved in pending:
            node_ids = file_nodes.get(str(resolved))
            if node_ids is not None:
                # Resolved to a parsed manifest file: link to its real nodes.
                for node_id in node_ids:
                    edges.append(
                        {
                            "from": overlay_id,
                            "to": node_id,
                            "type": "includes",
                            "confidence": 1.0,
                            "provenance": "EXTRACTED",
                        }
                    )
                continue
            if resolved.is_dir() and (
                (resolved / "kustomization.yaml").exists()
                or (resolved / "kustomization.yml").exists()
            ):
                # Resolved to another kustomize overlay/base directory.
                edges.append(
                    {
                        "from": overlay_id,
                        "to": f"kustomize/{rel_posix(resolved, self._root)}",
                        "type": "extends",
                        "confidence": 1.0,
                        "provenance": "EXTRACTED",
                    }
                )
            # else: unresolved (remote/URL/missing) — the stub node and its
            # `extends` edge were already emitted inline in parse_kustomize.
        self._helm._kustomize_pending = []
        return edges
