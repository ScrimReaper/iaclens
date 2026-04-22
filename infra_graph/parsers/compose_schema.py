"""Docker Compose file parser."""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

_yaml = YAML()
_yaml.preserve_quotes = True

_COMPOSE_FILENAMES = {
    "docker-compose.yml", "docker-compose.yaml",
    "compose.yml", "compose.yaml",
}


class ComposeParser:
    """Parse docker-compose.yml / compose.yaml files."""

    def is_compose_file(self, path: Path) -> bool:
        return path.name.lower() in _COMPOSE_FILENAMES

    def parse_file(self, path: Path) -> dict[str, Any]:
        """Parse a Docker Compose file."""
        nodes: list[dict] = []
        edges: list[dict] = []

        try:
            text = path.read_text(encoding="utf-8")
            doc = _yaml.load(text)
        except Exception as exc:
            warnings.warn(f"[compose_schema] Failed to parse {path}: {exc}")
            return {"nodes": nodes, "edges": edges}

        if not isinstance(doc, dict):
            return {"nodes": nodes, "edges": edges}

        file_str = str(path)
        project_name = path.parent.name or "compose"

        services = doc.get("services") or {}
        volumes = doc.get("volumes") or {}
        networks = doc.get("networks") or {}

        # Volume nodes (named volumes)
        for vol_name in volumes:
            vol_id = f"volume/{project_name}/{vol_name}"
            nodes.append(
                {
                    "id": vol_id,
                    "type": "volume",
                    "kind": "docker_volume",
                    "name": vol_name,
                    "file": file_str,
                    "line": None,
                    "labels": {},
                    "community_id": None,
                }
            )

        # Network nodes
        for net_name in networks:
            net_id = f"network/{project_name}/{net_name}"
            nodes.append(
                {
                    "id": net_id,
                    "type": "network",
                    "kind": "docker_network",
                    "name": net_name,
                    "file": file_str,
                    "line": None,
                    "labels": {},
                    "community_id": None,
                }
            )

        service_ids: dict[str, str] = {}

        for svc_name, svc_body in services.items():
            if not isinstance(svc_body, dict):
                svc_body = {}
            svc_id = f"service/{project_name}/{svc_name}"
            service_ids[svc_name] = svc_id

            image = svc_body.get("image") or svc_body.get("build") or ""
            if isinstance(image, dict):
                image = image.get("context", "")

            nodes.append(
                {
                    "id": svc_id,
                    "type": "service",
                    "kind": str(image) if image else "compose_service",
                    "name": svc_name,
                    "file": file_str,
                    "line": None,
                    "labels": {"project": project_name},
                    "community_id": None,
                }
            )

        # Second pass: edges
        for svc_name, svc_body in services.items():
            if not isinstance(svc_body, dict):
                continue
            svc_id = service_ids[svc_name]

            # depends_on edges
            deps_raw = svc_body.get("depends_on") or []
            if isinstance(deps_raw, list):
                dep_names = deps_raw
            elif isinstance(deps_raw, dict):
                dep_names = list(deps_raw.keys())
            else:
                dep_names = []

            for dep_name in dep_names:
                if dep_name in service_ids:
                    edges.append(
                        {
                            "from": svc_id,
                            "to": service_ids[dep_name],
                            "type": "depends_on",
                            "confidence": 1.0,
                            "provenance": "EXTRACTED",
                        }
                    )

            # Volume mounts
            vol_mounts = svc_body.get("volumes") or []
            for mount in vol_mounts:
                if not isinstance(mount, str):
                    continue
                vol_name = mount.split(":")[0].strip()
                # Named volume (not a bind mount path)
                if not vol_name.startswith("/") and not vol_name.startswith("."):
                    vol_id = f"volume/{project_name}/{vol_name}"
                    if vol_id in {n["id"] for n in nodes}:
                        edges.append(
                            {
                                "from": svc_id,
                                "to": vol_id,
                                "type": "shares_volume",
                                "confidence": 1.0,
                                "provenance": "EXTRACTED",
                            }
                        )

            # Network connections
            svc_nets = svc_body.get("networks") or []
            if isinstance(svc_nets, dict):
                svc_nets = list(svc_nets.keys())
            for net_name in svc_nets:
                net_id = f"network/{project_name}/{net_name}"
                if net_id in {n["id"] for n in nodes}:
                    edges.append(
                        {
                            "from": svc_id,
                            "to": net_id,
                            "type": "shares_network",
                            "confidence": 1.0,
                            "provenance": "EXTRACTED",
                        }
                    )

        return {"nodes": nodes, "edges": edges}
