"""Ansible playbook and task-file parser.

Stateful and path-aware: `parse_file` classifies each file by its path and
records nodes plus *pending* cross-file references (e.g. role -> task_file)
into accumulators. `finalize()` resolves everything that spans files and
returns the extra edges once every file has been parsed.
"""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from ._ids import qualified, rel_posix

_yaml = YAML()
_yaml.preserve_quotes = True


def _is_playbook(docs: Any) -> bool:
    """True if the YAML is a list where at least one item has a 'hosts' key."""
    if not isinstance(docs, list):
        return False
    return any(isinstance(item, dict) and "hosts" in item for item in docs)


def _is_task_file(docs: Any, path: Path) -> bool:
    """
    True if the YAML is a non-empty list of dicts with 'name' or 'block' keys
    (but no 'hosts' key) located under a tasks/ directory.
    """
    if not isinstance(docs, list) or not docs:
        return False
    if any(isinstance(item, dict) and "hosts" in item for item in docs):
        return False
    if not all(isinstance(item, dict) for item in docs):
        return False
    has_task_key = any(
        "name" in item or "block" in item or "include_tasks" in item or "import_tasks" in item
        for item in docs
    )
    if not has_task_key:
        return False
    # Require a tasks/ directory in the path to avoid false positives
    return "tasks" in path.parts


class AnsibleParser:
    """Parse Ansible playbook and task files.

    Stateful across a run: call `parse_file` for every file, then `finalize()`
    once at the end to resolve cross-file edges (e.g. role -> task_file).
    """

    def __init__(self, project_root: Path | None = None) -> None:
        # `project_root` defaults to cwd so the parser stays usable
        # standalone (e.g. existing single-file tests); real callers
        # (YAMLParser) always pass the actual project root.
        self._root = (project_root or Path.cwd()).resolve()

        # ── Accumulators (populated by parse_file, resolved by finalize) ────
        self._roles: dict[str, dict] = {}  # role_id -> role node
        self._task_files: dict[str, dict] = {}  # task_file_id -> task_file node
        self._role_task_pending: list[tuple[str, str]] = []  # (role_name, task_file_id)
        self._plays: dict[str, dict] = {}  # play_id -> play node
        self._role_uses: list[tuple[str, str]] = []  # (play_id, role_name)

    def is_ansible_file(self, path: Path) -> bool:
        """Return True if the file appears to be an Ansible playbook or task file."""
        if path.suffix not in (".yml", ".yaml"):
            return False
        try:
            text = path.read_text(encoding="utf-8")
            docs = _yaml.load(text)
        except Exception:
            return False
        return _is_playbook(docs) or _is_task_file(docs, path)

    def parse_file(self, path: Path) -> dict[str, Any]:
        """Parse an Ansible playbook or task file."""
        nodes: list[dict] = []
        edges: list[dict] = []

        try:
            text = path.read_text(encoding="utf-8")
            docs = _yaml.load(text)
        except Exception as exc:
            warnings.warn(f"[ansible_schema] Failed to parse {path}: {exc}")
            return {"nodes": nodes, "edges": edges}

        if _is_playbook(docs):
            return self._parse_playbook(path, docs)
        if _is_task_file(docs, path):
            return self._parse_task_file(path, docs)
        return {"nodes": nodes, "edges": edges}

    def finalize(self) -> list[dict]:
        """Resolve cross-file references collected while parsing.

        Task 1 scope: role -> task_file (`has_task`) for every task file
        discovered under `roles/<name>/tasks/`.
        """
        edges: list[dict] = []
        for role_name, task_file_id in self._role_task_pending:
            role_id = self._ensure_role(role_name)
            edges.append({
                "from": role_id,
                "to": task_file_id,
                "type": "has_task",
                "confidence": 1.0,
                "provenance": "EXTRACTED",
            })
        return edges

    # ── Playbook ───────────────────────────────────────────────────────────────

    def _parse_playbook(self, path: Path, plays: list) -> dict[str, Any]:
        nodes: list[dict] = []
        edges: list[dict] = []
        seen_ids: set[str] = set()
        file_str = str(path)
        rel = rel_posix(path, self._root)

        for play in plays:
            if not isinstance(play, dict):
                continue

            hosts_raw = play.get("hosts", "all")
            hosts = str(hosts_raw) if hosts_raw is not None else "all"
            play_name = play.get("name") or f"{path.stem}/{hosts}"
            play_id = qualified("play", rel, hosts)

            line = None
            try:
                line = play.lc.line + 1
            except AttributeError:
                pass

            if play_id not in seen_ids:
                play_node = {
                    "id": play_id,
                    "type": "play",
                    "kind": "ansible_play",
                    "name": play_name,
                    "file": file_str,
                    "line": line,
                    "labels": {"hosts": hosts},
                    "community_id": None,
                }
                nodes.append(play_node)
                seen_ids.add(play_id)
                self._plays[play_id] = play_node

            # roles → uses_role edges
            for role_entry in play.get("roles") or []:
                role_name = self._role_name(role_entry)
                if role_name:
                    role_id = self._ensure_role(role_name, nodes)
                    seen_ids.add(role_id)
                    self._role_uses.append((play_id, role_name))
                    edges.append({
                        "from": play_id,
                        "to": role_id,
                        "type": "uses_role",
                        "confidence": 1.0,
                        "provenance": "EXTRACTED",
                    })

            # tasks / pre_tasks / post_tasks → includes_tasks edges
            for section in ("tasks", "pre_tasks", "post_tasks"):
                for task in play.get(section) or []:
                    nodes_new, edges_new = self._extract_task_includes(
                        task, play_id, seen_ids, file_str
                    )
                    nodes.extend(nodes_new)
                    seen_ids.update(n["id"] for n in nodes_new)
                    edges.extend(edges_new)

        return {"nodes": nodes, "edges": edges}

    # ── Task file ─────────────────────────────────────────────────────────────

    def _parse_task_file(self, path: Path, tasks: list) -> dict[str, Any]:
        nodes: list[dict] = []
        edges: list[dict] = []
        file_str = str(path)
        rel = rel_posix(path, self._root)

        task_file_id = f"task_file/{rel}"
        task_file_node = {
            "id": task_file_id,
            "type": "task_file",
            "kind": "ansible_task_file",
            "name": path.stem,
            "file": file_str,
            "line": None,
            "labels": {},
            "community_id": None,
        }
        nodes.append(task_file_node)
        self._task_files[task_file_id] = task_file_node
        seen_ids: set[str] = {task_file_id}

        role_name = self._role_name_from_path(path)
        if role_name:
            role_id = self._ensure_role(role_name, nodes)
            seen_ids.add(role_id)
            self._role_task_pending.append((role_name, task_file_id))

        for task in tasks:
            nodes_new, edges_new = self._extract_task_includes(
                task, task_file_id, seen_ids, file_str
            )
            nodes.extend(nodes_new)
            seen_ids.update(n["id"] for n in nodes_new)
            edges.extend(edges_new)

        return {"nodes": nodes, "edges": edges}

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _ensure_role(self, role_name: str, nodes: list[dict] | None = None) -> str:
        """Return `role/<role_name>`, creating (and lazily emitting) the role
        node on first reference from any file."""
        role_id = f"role/{role_name}"
        if role_id not in self._roles:
            role_node = {
                "id": role_id,
                "type": "role",
                "kind": "ansible_role",
                "name": role_name,
                "file": f"roles/{role_name}",
                "line": None,
                "labels": {},
                "community_id": None,
            }
            self._roles[role_id] = role_node
            if nodes is not None:
                nodes.append(role_node)
        return role_id

    @staticmethod
    def _role_name_from_path(path: Path) -> str | None:
        """`roles/<name>/...` → `<name>`, else None."""
        parts = path.parts
        if "roles" not in parts:
            return None
        idx = parts.index("roles")
        if idx + 1 < len(parts):
            return parts[idx + 1]
        return None

    @staticmethod
    def _role_name(entry: Any) -> str | None:
        if isinstance(entry, str):
            return entry
        if isinstance(entry, dict):
            return entry.get("role") or entry.get("name")
        return None

    @staticmethod
    def _extract_task_includes(
        task: Any,
        owner_id: str,
        seen_ids: set[str],
        file_str: str,
    ) -> tuple[list[dict], list[dict]]:
        """Return (new_nodes, new_edges) for include_tasks/import_tasks in a task.

        Path resolution relative to the including file's directory (and block/
        rescue/always recursion) lands in WS1 Task 2; this keeps the naive
        stem-based target id for now.
        """
        nodes: list[dict] = []
        edges: list[dict] = []
        if not isinstance(task, dict):
            return nodes, edges
        for inc_key in ("include_tasks", "import_tasks"):
            ref = task.get(inc_key)
            if not ref:
                continue
            if isinstance(ref, dict):
                ref = ref.get("file") or ref.get("name")
            if not ref:
                continue
            target_stem = Path(str(ref)).stem
            target_id = f"task_file/{target_stem}"
            if target_id not in seen_ids:
                nodes.append({
                    "id": target_id,
                    "type": "task_file",
                    "kind": "ansible_task_file",
                    "name": target_stem,
                    "file": None,
                    "line": None,
                    "labels": {},
                    "community_id": None,
                })
            edges.append({
                "from": owner_id,
                "to": target_id,
                "type": "includes_tasks",
                "confidence": 1.0,
                "provenance": "EXTRACTED",
            })
        return nodes, edges
