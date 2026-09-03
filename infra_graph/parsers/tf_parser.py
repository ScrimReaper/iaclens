"""Terraform (.tf) file parser using python-hcl2."""

from __future__ import annotations

import re
import warnings
from pathlib import Path
from typing import Any

import hcl2

from ._ids import qualified, rel_posix

# Regex to extract ${...} interpolations
_INTERP_RE = re.compile(r"\$\{([^}]+)\}")

# Patterns for classifying interpolation targets
_VAR_RE = re.compile(r"^var\.(\w+)$")
_DATA_RE = re.compile(r"^data\.(\w+)\.(\w+)")
_LOCAL_RE = re.compile(r"^local\.(\w+)$")
_RESOURCE_RE = re.compile(r"^(\w+)\.(\w+)\.")

# Detect dynamic refs (string concatenation / complex expressions)
_DYNAMIC_RE = re.compile(r"[+\-*/]|format\(|join\(")

# HCL2 wraps string keys in double-quotes sometimes; strip them
_QUOTE_RE = re.compile(r'^"(.*)"$')


def _strip_quotes(s: str) -> str:
    """Strip surrounding double-quotes that python-hcl2 may leave on identifiers."""
    m = _QUOTE_RE.match(s)
    return m.group(1) if m else s


def _normalize_dep(dep: str, d: str) -> str:
    """
    Normalize a depends_on value to a directory-qualified node ID, resolved
    within directory `d` (Terraform references are directory/module scoped).
    Handles: ${aws_vpc.main} → resource/<d>#aws_vpc.main
             aws_vpc.main   → resource/<d>#aws_vpc.main
             var.x / local.x / data.t.n / module.m → same-dir qualified ids.
    """
    dep = dep.strip()
    # Strip ${...} wrapper
    m = re.match(r"^\$\{([^}]+)\}$", dep)
    if m:
        dep = m.group(1).strip()
    # Strip quotes
    dep = _strip_quotes(dep)

    if dep.startswith("var."):
        return qualified("variable", d, dep[len("var.") :])
    if dep.startswith("local."):
        return qualified("local", d, dep[len("local.") :])
    if dep.startswith("data."):
        parts = dep.split(".", 2)
        if len(parts) >= 3:
            return qualified("data", d, f"{parts[1]}.{parts[2]}")
        return qualified("data", d, dep[len("data.") :])
    if dep.startswith("module."):
        parts = dep.split(".")
        name = parts[1] if len(parts) >= 2 else dep[len("module.") :]
        return qualified("module", d, name)

    # Otherwise assume it's type.name → resource
    parts = dep.split(".")
    if len(parts) >= 2:
        return qualified("resource", d, f"{parts[0]}.{parts[1]}")
    return qualified("resource", d, dep)


def _extract_interpolations(value: Any) -> list[str]:
    """Recursively extract ${...} interpolation targets from any value."""
    results: list[str] = []
    if isinstance(value, str):
        for m in _INTERP_RE.finditer(value):
            results.append(m.group(1).strip())
    elif isinstance(value, dict):
        for v in value.values():
            results.extend(_extract_interpolations(v))
    elif isinstance(value, list):
        for item in value:
            results.extend(_extract_interpolations(item))
    return results


def _classify_interp(expr: str, d: str) -> tuple[str, str]:
    """Return (edge_type, target_id) for an interpolation expression, with
    the reference resolved within directory `d` (Terraform references are
    directory/module scoped). `module.<m>.<out>` is not yet resolved to the
    child module's directory here (Task 2); it falls through to the generic
    dotted-reference fallback and is qualified in `d` like everything else,
    without crashing."""
    if _DYNAMIC_RE.search(expr):
        return ("dynamic_ref", expr)

    m = _VAR_RE.match(expr)
    if m:
        return ("uses_var", qualified("variable", d, m.group(1)))

    m = _DATA_RE.match(expr)
    if m:
        return ("uses_data", qualified("data", d, f"{m.group(1)}.{m.group(2)}"))

    m = _LOCAL_RE.match(expr)
    if m:
        return ("uses_local", qualified("local", d, m.group(1)))

    m = _RESOURCE_RE.match(expr)
    if m:
        return ("references", qualified("resource", d, f"{m.group(1)}.{m.group(2)}"))

    # Fallback: type.name (2-segment, like aws_vpc.main)
    parts = expr.split(".")
    if len(parts) >= 2:
        return ("references", qualified("resource", d, f"{parts[0]}.{parts[1]}"))

    return ("references", expr)


class TerraformParser:
    """Parse Terraform .tf files and emit graph nodes + edges."""

    def __init__(self, project_root: Path) -> None:
        self._root = project_root.resolve()

    def parse_file(self, path: Path) -> dict[str, Any]:
        """
        Parse a single .tf file.

        Returns a dict with:
          - nodes: list of node dicts
          - edges: list of edge dicts
        """
        nodes: list[dict] = []
        edges: list[dict] = []

        try:
            text = path.read_text(encoding="utf-8")
            data = hcl2.loads(text)
        except Exception as exc:
            warnings.warn(f"[tf_parser] Failed to parse {path}: {exc}")
            return {"nodes": nodes, "edges": edges}

        file_str = str(path)
        # Directory-qualify every node/reference in this file to its module
        # directory `d` (root-level files → "."), so same-named blocks in
        # different module directories don't collide.
        d = rel_posix(path.parent, self._root)

        # ── resource blocks ─────────────────────────────────────────────────
        for resource_block in data.get("resource", []):
            for res_type_raw, instances in resource_block.items():
                res_type = _strip_quotes(res_type_raw)
                for res_name_raw, body in instances.items():
                    res_name = _strip_quotes(res_name_raw)
                    node_id = qualified("resource", d, f"{res_type}.{res_name}")
                    nodes.append(
                        {
                            "id": node_id,
                            "type": "resource",
                            "kind": res_type,
                            "name": res_name,
                            "file": file_str,
                            "line": None,
                            "labels": {},
                            "community_id": None,
                        }
                    )
                    # depends_on explicit
                    for dep in _flatten_list(body.get("depends_on", [])):
                        dep_str = _normalize_dep(str(dep), d)
                        if dep_str:
                            edges.append(
                                {
                                    "from": node_id,
                                    "to": dep_str,
                                    "type": "depends_on",
                                    "confidence": 1.0,
                                    "provenance": "EXTRACTED",
                                }
                            )
                    # interpolation refs
                    for expr in _extract_interpolations(body):
                        edge_type, target = _classify_interp(expr, d)
                        if target and target != node_id:
                            edges.append(
                                {
                                    "from": node_id,
                                    "to": target,
                                    "type": edge_type,
                                    "confidence": 0.5 if edge_type == "dynamic_ref" else 1.0,
                                    "provenance": "AMBIGUOUS" if edge_type == "dynamic_ref" else "EXTRACTED",
                                }
                            )

        # ── variable blocks ──────────────────────────────────────────────────
        for var_block in data.get("variable", []):
            for var_name_raw, _body in var_block.items():
                var_name = _strip_quotes(var_name_raw)
                node_id = qualified("variable", d, var_name)
                nodes.append(
                    {
                        "id": node_id,
                        "type": "variable",
                        "kind": "variable",
                        "name": var_name,
                        "file": file_str,
                        "line": None,
                        "labels": {},
                        "community_id": None,
                    }
                )

        # ── output blocks ────────────────────────────────────────────────────
        for out_block in data.get("output", []):
            for out_name_raw, body in out_block.items():
                out_name = _strip_quotes(out_name_raw)
                output_body = body if isinstance(body, dict) else {}
                node_id = qualified("output", d, out_name)
                nodes.append(
                    {
                        "id": node_id,
                        "type": "output",
                        "kind": "output",
                        "name": out_name,
                        "file": file_str,
                        "line": None,
                        "labels": {},
                        "community_id": None,
                        "expression": str(output_body.get("value", "")),
                    }
                )
                for expr in _extract_interpolations(body):
                    edge_type, target = _classify_interp(expr, d)
                    if target and target != node_id:
                        edges.append(
                            {
                                "from": node_id,
                                "to": target,
                                "type": edge_type,
                                "confidence": 0.5 if edge_type == "dynamic_ref" else 1.0,
                                "provenance": "AMBIGUOUS" if edge_type == "dynamic_ref" else "EXTRACTED",
                            }
                        )

        # ── data blocks ──────────────────────────────────────────────────────
        for data_block in data.get("data", []):
            for data_type_raw, instances in data_block.items():
                data_type = _strip_quotes(data_type_raw)
                for data_name_raw, body in instances.items():
                    data_name = _strip_quotes(data_name_raw)
                    node_id = qualified("data", d, f"{data_type}.{data_name}")
                    nodes.append(
                        {
                            "id": node_id,
                            "type": "data",
                            "kind": data_type,
                            "name": data_name,
                            "file": file_str,
                            "line": None,
                            "labels": {},
                            "community_id": None,
                        }
                    )
                    for expr in _extract_interpolations(body):
                        edge_type, target = _classify_interp(expr, d)
                        if target and target != node_id:
                            edges.append(
                                {
                                    "from": node_id,
                                    "to": target,
                                    "type": edge_type,
                                    "confidence": 0.5 if edge_type == "dynamic_ref" else 1.0,
                                    "provenance": "AMBIGUOUS" if edge_type == "dynamic_ref" else "EXTRACTED",
                                }
                            )

        # ── locals blocks ────────────────────────────────────────────────────
        for locals_block in data.get("locals", []):
            for local_name_raw, body in locals_block.items():
                local_name = _strip_quotes(local_name_raw)
                # Skip internal hcl2 marker keys
                if local_name.startswith("__") and local_name.endswith("__"):
                    continue
                node_id = qualified("local", d, local_name)
                nodes.append(
                    {
                        "id": node_id,
                        "type": "local",
                        "kind": "local",
                        "name": local_name,
                        "file": file_str,
                        "line": None,
                        "labels": {},
                        "community_id": None,
                    }
                )
                for expr in _extract_interpolations({local_name: body}):
                    edge_type, target = _classify_interp(expr, d)
                    if target and target != node_id:
                        edges.append(
                            {
                                "from": node_id,
                                "to": target,
                                "type": edge_type,
                                "confidence": 0.5 if edge_type == "dynamic_ref" else 1.0,
                                "provenance": "AMBIGUOUS" if edge_type == "dynamic_ref" else "EXTRACTED",
                            }
                        )

        # ── provider blocks ──────────────────────────────────────────────────
        for prov_block in data.get("provider", []):
            for prov_name_raw, _body in prov_block.items():
                prov_name = _strip_quotes(prov_name_raw)
                node_id = qualified("provider", d, prov_name)
                nodes.append(
                    {
                        "id": node_id,
                        "type": "provider",
                        "kind": "provider",
                        "name": prov_name,
                        "file": file_str,
                        "line": None,
                        "labels": {},
                        "community_id": None,
                    }
                )

        # ── module blocks ────────────────────────────────────────────────────
        for module_block in data.get("module", []):
            for mod_name_raw, body in module_block.items():
                mod_name = _strip_quotes(mod_name_raw)
                node_id = qualified("module", d, mod_name)
                nodes.append(
                    {
                        "id": node_id,
                        "type": "module",
                        "kind": body.get("source", "unknown"),
                        "name": mod_name,
                        "file": file_str,
                        "line": None,
                        "labels": {},
                        "community_id": None,
                    }
                )
                # passes_input for each module argument (excluding source/version/providers)
                skip_keys = {"source", "version", "providers", "depends_on"}
                for key, val in body.items():
                    if key in skip_keys:
                        continue
                    for expr in _extract_interpolations(val):
                        edge_type, target = _classify_interp(expr, d)
                        if target and target != node_id:
                            edges.append(
                                {
                                    "from": node_id,
                                    "to": target,
                                    "type": "passes_input",
                                    "confidence": 1.0,
                                    "provenance": "EXTRACTED",
                                }
                            )
                # explicit depends_on
                for dep in _flatten_list(body.get("depends_on", [])):
                    dep_str = _normalize_dep(str(dep), d)
                    if dep_str:
                        edges.append(
                            {
                                "from": node_id,
                                "to": dep_str,
                                "type": "depends_on",
                                "confidence": 1.0,
                                "provenance": "EXTRACTED",
                            }
                        )

        return {"nodes": nodes, "edges": edges}


def _flatten_list(val: Any) -> list:
    """Flatten potentially nested lists."""
    if isinstance(val, list):
        result = []
        for item in val:
            result.extend(_flatten_list(item))
        return result
    return [val] if val is not None else []
