"""GitHub Actions workflow parser."""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

_yaml = YAML()
_yaml.preserve_quotes = True


class ActionsParser:
    """Parse .github/workflows/*.yml files."""

    def is_actions_file(self, path: Path) -> bool:
        """Return True if the path looks like a GitHub Actions workflow."""
        parts = path.parts
        try:
            gh_idx = next(i for i, p in enumerate(parts) if p == ".github")
            if len(parts) > gh_idx + 1 and parts[gh_idx + 1] == "workflows":
                return path.suffix in (".yml", ".yaml")
        except StopIteration:
            pass
        return False

    def parse_file(self, path: Path) -> dict[str, Any]:
        """Parse a GitHub Actions workflow file."""
        nodes: list[dict] = []
        edges: list[dict] = []

        try:
            text = path.read_text(encoding="utf-8")
            doc = _yaml.load(text)
        except Exception as exc:
            warnings.warn(f"[actions_schema] Failed to parse {path}: {exc}")
            return {"nodes": nodes, "edges": edges}

        if not isinstance(doc, dict):
            return {"nodes": nodes, "edges": edges}

        workflow_name = doc.get("name") or path.stem
        file_str = str(path)

        # Workflow-level node
        workflow_id = f"workflow/{workflow_name}"
        nodes.append(
            {
                "id": workflow_id,
                "type": "workflow",
                "kind": "workflow",
                "name": workflow_name,
                "file": file_str,
                "line": None,
                "labels": {},
                "community_id": None,
            }
        )

        jobs = doc.get("jobs") or {}
        if not isinstance(jobs, dict):
            return {"nodes": nodes, "edges": edges}

        job_ids: dict[str, str] = {}  # job_key → node_id

        for job_key, job_body in jobs.items():
            if not isinstance(job_body, dict):
                continue
            job_name = job_body.get("name") or job_key
            job_node_id = f"job/{workflow_name}/{job_key}"
            job_ids[job_key] = job_node_id

            nodes.append(
                {
                    "id": job_node_id,
                    "type": "job",
                    "kind": "job",
                    "name": job_name,
                    "file": file_str,
                    "line": None,
                    "labels": {"workflow": workflow_name},
                    "community_id": None,
                }
            )

            # Job belongs to workflow
            edges.append(
                {
                    "from": workflow_id,
                    "to": job_node_id,
                    "type": "contains",
                    "confidence": 1.0,
                    "provenance": "EXTRACTED",
                }
            )

            # needs: → depends_on edges (resolve after all jobs seen)
            needs_raw = job_body.get("needs") or []
            if isinstance(needs_raw, str):
                needs_raw = [needs_raw]
            for needed_key in needs_raw:
                # We'll store as placeholder, resolve in second pass
                edges.append(
                    {
                        "from": job_node_id,
                        "to": f"__needs__{workflow_name}__{needed_key}",
                        "type": "depends_on",
                        "confidence": 1.0,
                        "provenance": "EXTRACTED",
                        "_resolve": True,
                    }
                )

            # steps: extract uses: references
            steps = job_body.get("steps") or []
            for step_idx, step in enumerate(steps):
                if not isinstance(step, dict):
                    continue
                step_name = step.get("name") or step.get("id") or f"step_{step_idx}"
                step_id = f"step/{workflow_name}/{job_key}/{step_idx}"

                nodes.append(
                    {
                        "id": step_id,
                        "type": "step",
                        "kind": "step",
                        "name": step_name,
                        "file": file_str,
                        "line": None,
                        "labels": {"job": job_key, "workflow": workflow_name},
                        "community_id": None,
                    }
                )
                edges.append(
                    {
                        "from": job_node_id,
                        "to": step_id,
                        "type": "contains",
                        "confidence": 1.0,
                        "provenance": "EXTRACTED",
                    }
                )

                uses = step.get("uses")
                if uses:
                    action_id = f"action/{uses}"
                    # Ensure action node exists (might be shared)
                    nodes.append(
                        {
                            "id": action_id,
                            "type": "action",
                            "kind": "external_action",
                            "name": uses,
                            "file": None,
                            "line": None,
                            "labels": {},
                            "community_id": None,
                        }
                    )
                    edges.append(
                        {
                            "from": step_id,
                            "to": action_id,
                            "type": "uses_action",
                            "confidence": 1.0,
                            "provenance": "EXTRACTED",
                        }
                    )

                # secrets references in env / with
                for key in ("env", "with"):
                    val = step.get(key) or {}
                    if isinstance(val, dict):
                        for v in val.values():
                            if isinstance(v, str) and "secrets." in v:
                                import re
                                for sm in re.finditer(r"secrets\.(\w+)", v):
                                    secret_name = sm.group(1)
                                    secret_id = f"secret_ref/{secret_name}"
                                    nodes.append(
                                        {
                                            "id": secret_id,
                                            "type": "secret_ref",
                                            "kind": "github_secret",
                                            "name": secret_name,
                                            "file": None,
                                            "line": None,
                                            "labels": {},
                                            "community_id": None,
                                        }
                                    )
                                    edges.append(
                                        {
                                            "from": step_id,
                                            "to": secret_id,
                                            "type": "uses_secret",
                                            "confidence": 1.0,
                                            "provenance": "EXTRACTED",
                                        }
                                    )

        # Resolve needs: references
        resolved_edges = []
        for edge in edges:
            if edge.get("_resolve"):
                placeholder = edge["to"]
                # placeholder format: __needs__{workflow}__{job_key}
                parts = placeholder.split("__")
                if len(parts) >= 4:
                    needed_key = parts[3]
                    resolved_to = job_ids.get(needed_key, f"job/{workflow_name}/{needed_key}")
                    edge = {**edge, "to": resolved_to}
                edge_clean = {k: v for k, v in edge.items() if k != "_resolve"}
                resolved_edges.append(edge_clean)
            else:
                resolved_edges.append(edge)

        # Deduplicate action nodes
        seen_ids: set[str] = set()
        unique_nodes: list[dict] = []
        for n in nodes:
            if n["id"] not in seen_ids:
                seen_ids.add(n["id"])
                unique_nodes.append(n)

        return {"nodes": unique_nodes, "edges": resolved_edges}
