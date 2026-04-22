"""Helm chart and Kustomize overlay parser."""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

_yaml = YAML()
_yaml.preserve_quotes = True


class HelmParser:
    """Parse Helm Chart.yaml, values*.yaml, and kustomization.yaml files."""

    def is_chart_file(self, path: Path) -> bool:
        return path.name == "Chart.yaml"

    def is_values_file(self, path: Path) -> bool:
        return path.name.startswith("values") and path.suffix in (".yml", ".yaml")

    def is_kustomize_file(self, path: Path) -> bool:
        return path.name in ("kustomization.yaml", "kustomization.yml")

    def parse_chart(self, path: Path) -> dict[str, Any]:
        """Parse a Helm Chart.yaml."""
        nodes: list[dict] = []
        edges: list[dict] = []

        try:
            text = path.read_text(encoding="utf-8")
            doc = _yaml.load(text)
        except Exception as exc:
            warnings.warn(f"[helm_schema] Failed to parse {path}: {exc}")
            return {"nodes": nodes, "edges": edges}

        if not isinstance(doc, dict):
            return {"nodes": nodes, "edges": edges}

        chart_name = doc.get("name") or path.parent.name
        chart_version = doc.get("version") or "unknown"
        chart_id = f"helm_chart/{chart_name}"

        nodes.append(
            {
                "id": chart_id,
                "type": "helm_chart",
                "kind": doc.get("type", "application"),
                "name": chart_name,
                "file": str(path),
                "line": None,
                "labels": {"version": chart_version},
                "community_id": None,
            }
        )

        # Chart dependencies (from Chart.yaml dependencies block)
        for dep in doc.get("dependencies") or []:
            if not isinstance(dep, dict):
                continue
            dep_name = dep.get("name") or dep.get("alias", "")
            dep_repo = dep.get("repository", "")
            if dep_name:
                dep_id = f"helm_chart/{dep_name}"
                nodes.append(
                    {
                        "id": dep_id,
                        "type": "helm_chart",
                        "kind": "dependency",
                        "name": dep_name,
                        "file": None,
                        "line": None,
                        "labels": {"repository": dep_repo},
                        "community_id": None,
                    }
                )
                edges.append(
                    {
                        "from": chart_id,
                        "to": dep_id,
                        "type": "depends_on",
                        "confidence": 1.0,
                        "provenance": "EXTRACTED",
                    }
                )

        return {"nodes": nodes, "edges": edges}

    def parse_values(self, path: Path, chart_id: str | None = None) -> dict[str, Any]:
        """Parse a values*.yaml file and emit an overrides edge."""
        nodes: list[dict] = []
        edges: list[dict] = []

        if chart_id is None:
            # Infer chart from parent directory
            chart_name = path.parent.name
            chart_id = f"helm_chart/{chart_name}"

        values_id = f"helm_values/{path.stem}"
        nodes.append(
            {
                "id": values_id,
                "type": "helm_values",
                "kind": "values_file",
                "name": path.stem,
                "file": str(path),
                "line": None,
                "labels": {},
                "community_id": None,
            }
        )
        edges.append(
            {
                "from": values_id,
                "to": chart_id,
                "type": "overrides",
                "confidence": 1.0,
                "provenance": "EXTRACTED",
            }
        )
        return {"nodes": nodes, "edges": edges}

    def parse_kustomize(self, path: Path) -> dict[str, Any]:
        """Parse a kustomization.yaml file."""
        nodes: list[dict] = []
        edges: list[dict] = []

        try:
            text = path.read_text(encoding="utf-8")
            doc = _yaml.load(text)
        except Exception as exc:
            warnings.warn(f"[helm_schema] Failed to parse {path}: {exc}")
            return {"nodes": nodes, "edges": edges}

        if not isinstance(doc, dict):
            return {"nodes": nodes, "edges": edges}

        overlay_name = str(path.parent.name)
        overlay_id = f"kustomize/{overlay_name}"

        nodes.append(
            {
                "id": overlay_id,
                "type": "kustomize",
                "kind": "overlay",
                "name": overlay_name,
                "file": str(path),
                "line": None,
                "labels": {},
                "community_id": None,
            }
        )

        # bases (older API) and resources
        for key in ("bases", "resources"):
            for ref in doc.get(key) or []:
                if not isinstance(ref, str):
                    continue
                ref_name = ref.rstrip("/").split("/")[-1]
                ref_id = f"kustomize/{ref_name}"
                nodes.append(
                    {
                        "id": ref_id,
                        "type": "kustomize",
                        "kind": "base",
                        "name": ref_name,
                        "file": None,
                        "line": None,
                        "labels": {},
                        "community_id": None,
                    }
                )
                edges.append(
                    {
                        "from": overlay_id,
                        "to": ref_id,
                        "type": "extends",
                        "confidence": 1.0,
                        "provenance": "EXTRACTED",
                    }
                )

        # patches
        for patch in doc.get("patches") or doc.get("patchesStrategicMerge") or []:
            if isinstance(patch, str):
                patch_name = patch.rstrip("/").split("/")[-1]
            elif isinstance(patch, dict):
                patch_name = (patch.get("path") or "").rstrip("/").split("/")[-1]
            else:
                continue
            if patch_name:
                patch_id = f"kustomize_patch/{patch_name}"
                nodes.append(
                    {
                        "id": patch_id,
                        "type": "kustomize_patch",
                        "kind": "patch",
                        "name": patch_name,
                        "file": None,
                        "line": None,
                        "labels": {},
                        "community_id": None,
                    }
                )
                edges.append(
                    {
                        "from": overlay_id,
                        "to": patch_id,
                        "type": "patches",
                        "confidence": 1.0,
                        "provenance": "EXTRACTED",
                    }
                )

        return {"nodes": nodes, "edges": edges}

    def parse_file(self, path: Path) -> dict[str, Any] | None:
        """Dispatch to correct parse method based on filename."""
        if self.is_chart_file(path):
            return self.parse_chart(path)
        if self.is_values_file(path):
            return self.parse_values(path)
        if self.is_kustomize_file(path):
            return self.parse_kustomize(path)
        return None
