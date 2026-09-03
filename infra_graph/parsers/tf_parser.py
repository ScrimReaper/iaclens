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
_MODULE_OUTPUT_RE = re.compile(r"^module\.(\w+)\.(\w+)")

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
        # An output-specific depends_on (module.<m>.<out>) collapses to a
        # dependency on the whole module block, not the child output.
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
    directory/module scoped). `module.<m>.<out>` is handled separately by
    callers (queued as a pending cross-module reference and resolved in
    `TerraformParser.finalize()`), so it never reaches this function."""
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
        # module_id -> resolved child directory (None for non-local/registry
        # sources), populated as module blocks are parsed across all files.
        self._module_children: dict[str, str | None] = {}
        # Pending cross-file resolution, drained by finalize():
        #   modules:          (module_id, dir d, child dir or None, [input arg names])
        #   module outputs:   (from_id, dir d, module name, output name)
        self._pending_modules: list[tuple[str, str, str | None, list[str]]] = []
        self._pending_module_outputs: list[tuple[str, str, str, str]] = []

    def _resolve_interp_edges(
        self,
        node_id: str,
        d: str,
        exprs: list[str],
        edge_type_override: str | None = None,
    ) -> list[dict]:
        """Classify each interpolation expression into an edge dict. A
        `module.<m>.<out>` reference is not resolvable within a single file
        (the child module may not be parsed yet), so it is queued as a
        pending cross-module reference instead and resolved in `finalize()`.
        """
        out: list[dict] = []
        for expr in exprs:
            mo = _MODULE_OUTPUT_RE.match(expr)
            if mo:
                self._pending_module_outputs.append((node_id, d, mo.group(1), mo.group(2)))
                continue
            edge_type, target = _classify_interp(expr, d)
            if edge_type_override:
                edge_type = edge_type_override
            if target and target != node_id:
                out.append(
                    {
                        "from": node_id,
                        "to": target,
                        "type": edge_type,
                        "confidence": 0.5 if edge_type == "dynamic_ref" else 1.0,
                        "provenance": "AMBIGUOUS" if edge_type == "dynamic_ref" else "EXTRACTED",
                    }
                )
        return out

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
                    edges.extend(
                        self._resolve_interp_edges(node_id, d, _extract_interpolations(body))
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
                edges.extend(
                    self._resolve_interp_edges(node_id, d, _extract_interpolations(body))
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
                    edges.extend(
                        self._resolve_interp_edges(node_id, d, _extract_interpolations(body))
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
                edges.extend(
                    self._resolve_interp_edges(
                        node_id, d, _extract_interpolations({local_name: body})
                    )
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
                source_raw = body.get("source")
                source = _strip_quotes(str(source_raw)) if source_raw is not None else None
                # Only a local relative source resolves to a child module dir;
                # registry/git sources have no on-disk child to link to.
                child_dir: str | None = None
                if source and (source.startswith("./") or source.startswith("../")):
                    child_dir = rel_posix((path.parent / source).resolve(), self._root)
                self._module_children[node_id] = child_dir
                nodes.append(
                    {
                        "id": node_id,
                        "type": "module",
                        "kind": source or "unknown",
                        "name": mod_name,
                        "file": file_str,
                        "line": None,
                        "labels": {},
                        "community_id": None,
                    }
                )
                # passes_input for each module argument (excluding source/version/providers).
                # Same-dir targets (e.g. var.x in this file) are recorded here;
                # finalize() additionally links each arg name to the CHILD
                # module's own variable of that name, once source is resolved.
                skip_keys = {"source", "version", "providers", "depends_on"}
                arg_names: list[str] = []
                input_exprs: list[str] = []
                for key, val in body.items():
                    # Skip explicit meta-args and hcl2's internal __x__ markers
                    # (e.g. __is_block__), which are not real module inputs.
                    if key in skip_keys or (key.startswith("__") and key.endswith("__")):
                        continue
                    arg_names.append(key)
                    input_exprs.extend(_extract_interpolations(val))
                edges.extend(
                    self._resolve_interp_edges(
                        node_id, d, input_exprs, edge_type_override="passes_input"
                    )
                )
                self._pending_modules.append((node_id, d, child_dir, arg_names))
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

    def finalize(self) -> list[dict]:
        """
        Call after every .tf file has been parsed. Resolves cross-directory
        module references that a single-file pass cannot: a module's inputs
        against its child module's variables, and `module.<m>.<out>` reads
        against the child module's output. Edges-only; drains (clears) the
        pending accumulators, so a second call returns nothing new.
        """
        edges: list[dict] = []

        for module_id, _d, child_dir, arg_names in self._pending_modules:
            if child_dir is None:
                continue
            for arg in arg_names:
                edges.append(
                    {
                        "from": module_id,
                        "to": qualified("variable", child_dir, arg),
                        "type": "passes_input",
                        "confidence": 1.0,
                        "provenance": "EXTRACTED",
                    }
                )
        self._pending_modules.clear()

        for from_id, d, mod_name, out_name in self._pending_module_outputs:
            child_dir = self._module_children.get(qualified("module", d, mod_name))
            if child_dir is None:
                continue
            edges.append(
                {
                    "from": from_id,
                    "to": qualified("output", child_dir, out_name),
                    "type": "uses_module_output",
                    "confidence": 1.0,
                    "provenance": "EXTRACTED",
                }
            )
        self._pending_module_outputs.clear()

        return edges


def _flatten_list(val: Any) -> list:
    """Flatten potentially nested lists."""
    if isinstance(val, list):
        result = []
        for item in val:
            result.extend(_flatten_list(item))
        return result
    return [val] if val is not None else []
