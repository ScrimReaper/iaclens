"""Ansible playbook and task-file parser.

Stateful and path-aware: `parse_file` classifies each file by its path and
records nodes plus *pending* cross-file references (e.g. role -> task_file)
into accumulators. `finalize()` resolves everything that spans files and
returns the extra edges once every file has been parsed.
"""

from __future__ import annotations

import re
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


def _is_task_like(docs: Any) -> bool:
    """
    True if the YAML is a non-empty list of dicts with 'name' or 'block' keys
    (but no 'hosts' key). Shared shape check for both task files and handler
    files — they only differ by which directory they live in.
    """
    if not isinstance(docs, list) or not docs:
        return False
    if any(isinstance(item, dict) and "hosts" in item for item in docs):
        return False
    if not all(isinstance(item, dict) for item in docs):
        return False
    return any(
        "name" in item or "block" in item or "include_tasks" in item or "import_tasks" in item
        for item in docs
    )


def _is_task_file(docs: Any, path: Path) -> bool:
    """Task-like YAML located under a tasks/ directory."""
    # Require a tasks/ directory in the path to avoid false positives
    return _is_task_like(docs) and "tasks" in path.parts


def _is_handler_file(docs: Any, path: Path) -> bool:
    """Task-like YAML located under a handlers/ directory."""
    return _is_task_like(docs) and "handlers" in path.parts


def _is_group_vars_path(path: Path) -> bool:
    """`group_vars/<g>.yml` or `group_vars/<g>/*.yml` — path-only, no content
    sniff (these files are plain mappings, not task lists)."""
    return "group_vars" in path.parts


def _is_host_vars_path(path: Path) -> bool:
    """`host_vars/<h>.yml` or `host_vars/<h>/*.yml` — path-only."""
    return "host_vars" in path.parts


_VARS_HOST_SPLIT_RE = re.compile(r"[,:\s]+")


def _hosts_tokens(hosts: str) -> list[str]:
    """Split a play's `hosts:` string on `,`/`:`/whitespace into tokens for a
    plain string match against a group or host name. No group-pattern math
    (globs, `&`/`!` operators, etc.) — just the literal tokens Ansible's
    inventory patterns most commonly use."""
    return [t for t in _VARS_HOST_SPLIT_RE.split(hosts.strip()) if t]


def _normalize_hosts(hosts_raw: Any) -> str:
    """Normalize a play's raw `hosts:` value to a single comma-joined string,
    *before* it's used for the play id, the play node's `hosts` label, or
    `_hosts_tokens` matching in `finalize()`.

    Ansible allows `hosts:` to be a YAML list (`hosts: [web1, web2]`) as well
    as a scalar string (`hosts: web1,web2` or `hosts: webservers`). Both forms
    must tokenize to the same host/group names — `str([...])` would instead
    stringify to `"['web1', 'web2']"`, which `_hosts_tokens` can't split
    sensibly, silently dropping the `uses_vars` match for list-form hosts.
    """
    if hosts_raw is None:
        return "all"
    if isinstance(hosts_raw, list):
        return ",".join(str(h) for h in hosts_raw)
    return str(hosts_raw)


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

        # (owner_id, including_file_dir, ref, edge_type) — resolved in finalize()
        # once every file's task_file id is known, so path-only includes
        # (e.g. `include_tasks: setup.yml`) resolve to the qualified id
        # regardless of parse order.
        self._include_pending: list[tuple[str, Path, str, str]] = []
        # (owner_id, role_name) for include_role/import_role — role ids don't
        # depend on parse order, but we still resolve in finalize() so the
        # role node is guaranteed to exist even if referenced before any of
        # its own files are parsed.
        self._include_role_pending: list[tuple[str, str]] = []

        # Handlers (Task 3): role-scoped handler nodes + notify resolution.
        self._handlers: dict[tuple[str, str], str] = {}  # (role, handler_name) -> handler_id
        # (role, listen_topic) -> [handler_id, ...] — a `listen:` topic is an
        # alternate match key: multiple handlers can share one topic, and a
        # single `notify` can hit all of them.
        self._handler_listen: dict[tuple[str, str], list[str]] = {}
        self._role_handler_pending: list[tuple[str, str]] = []  # (role_name, handler_id)
        # (owner_id, handler_name, role_name) — role_name is None for
        # notify found outside any role (e.g. playbook-level tasks), which
        # this schema doesn't attempt to resolve (no role scope to search).
        self._notify_pending: list[tuple[str, str, str | None]] = []

        # Vars (Task 4): group_vars/host_vars/role-defaults/role-vars nodes,
        # plus pending links resolved in finalize() (group/host -> play by
        # host-string match; role -> its own defaults/vars file).
        self._vars: dict[str, dict] = {}  # vars_id -> vars node
        self._group_vars: dict[str, str] = {}  # group_name -> vars_id
        self._host_vars: dict[str, str] = {}  # host_name -> vars_id
        self._role_vars_pending: list[tuple[str, str]] = []  # (role_name, vars_id)

    def is_ansible_file(self, path: Path) -> bool:
        """Return True if the file appears to be an Ansible playbook, task
        file, or vars file (group_vars/host_vars/role defaults/role vars).

        The vars cases are decided on path alone, *before* any content sniff:
        those files are plain mappings, not task lists, so the content-shape
        checks below (`_is_playbook`/`_is_task_file`/`_is_handler_file`) would
        never recognize them — the path is the only reliable signal.
        """
        if path.suffix not in (".yml", ".yaml"):
            return False
        if _is_group_vars_path(path) or _is_host_vars_path(path):
            return True
        role_name = self._role_name_from_path(path)
        if role_name and self._role_vars_kind(path):
            return True
        try:
            text = path.read_text(encoding="utf-8")
            docs = _yaml.load(text)
        except Exception:
            return False
        return _is_playbook(docs) or _is_task_file(docs, path) or _is_handler_file(docs, path)

    def parse_file(self, path: Path) -> dict[str, Any]:
        """Parse an Ansible playbook, task file, handler file, or vars file."""
        nodes: list[dict] = []
        edges: list[dict] = []

        # ── Vars files (path-only classification, see is_ansible_file) ──────
        if _is_group_vars_path(path):
            return self._parse_group_vars_file(path)
        if _is_host_vars_path(path):
            return self._parse_host_vars_file(path)
        role_name = self._role_name_from_path(path)
        role_vars_kind = self._role_vars_kind(path) if role_name else None
        if role_name and role_vars_kind:
            return self._parse_role_vars_file(path, role_name, role_vars_kind)

        try:
            text = path.read_text(encoding="utf-8")
            docs = _yaml.load(text)
        except Exception as exc:
            warnings.warn(f"[ansible_schema] Failed to parse {path}: {exc}")
            return {"nodes": nodes, "edges": edges}

        if _is_playbook(docs):
            return self._parse_playbook(path, docs)
        if _is_handler_file(docs, path):
            return self._parse_handler_file(path, docs)
        if _is_task_file(docs, path):
            return self._parse_task_file(path, docs)
        return {"nodes": nodes, "edges": edges}

    def finalize(self) -> list[dict]:
        """Resolve cross-file references collected while parsing.

        - role -> task_file (`has_task`) for every task file discovered
          under `roles/<name>/tasks/` (Task 1).
        - include_tasks/import_tasks -> task_file, resolved by path relative
          to the including file's directory (Task 2).
        - include_role/import_role -> role (Task 2).
        - role -> handler (`has_handler`) for every handler discovered under
          `roles/<name>/handlers/` (Task 3).
        - notify -> handler (`notifies`), resolved by handler name (falling
          back to a `listen:` topic match) within the notifying task's role
          (Task 3).
        - role -> vars (`uses_vars`) for every `defaults/*.yml`/`vars/*.yml`
          discovered under `roles/<name>/` (Task 4).
        - group_vars/host_vars -> play (`uses_vars`), resolved by matching
          the group/host name against the play's `hosts:` string (Task 4).

        Idempotent: pending lists are cleared after resolution, so a second
        `finalize()` call (or a stray double-call from a caller) emits no
        duplicate edges.
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
        self._role_task_pending.clear()

        for owner_id, including_dir, ref, edge_type in self._include_pending:
            target_path = (including_dir / ref).resolve()
            target_rel = rel_posix(target_path, self._root)
            target_id = f"task_file/{target_rel}"
            if target_id not in self._task_files:
                # Stub node: the include target was never parsed as its own
                # file (missing, or outside the walked tree) — still emit the
                # edge, but make sure `target_id` resolves to *something*.
                self._task_files[target_id] = {
                    "id": target_id,
                    "type": "task_file",
                    "kind": "ansible_task_file",
                    "name": target_path.stem,
                    "file": None,
                    "line": None,
                    "labels": {},
                    "community_id": None,
                }
            edges.append({
                "from": owner_id,
                "to": target_id,
                "type": edge_type,
                "confidence": 1.0,
                "provenance": "EXTRACTED",
            })
        self._include_pending.clear()

        for owner_id, role_name in self._include_role_pending:
            role_id = self._ensure_role(role_name)
            edges.append({
                "from": owner_id,
                "to": role_id,
                "type": "includes_role",
                "confidence": 1.0,
                "provenance": "EXTRACTED",
            })
        self._include_role_pending.clear()

        for role_name, handler_id in self._role_handler_pending:
            role_id = self._ensure_role(role_name)
            edges.append({
                "from": role_id,
                "to": handler_id,
                "type": "has_handler",
                "confidence": 1.0,
                "provenance": "EXTRACTED",
            })
        self._role_handler_pending.clear()

        for owner_id, handler_name, role_name in self._notify_pending:
            for handler_id in self._resolve_notify(role_name, handler_name):
                edges.append({
                    "from": owner_id,
                    "to": handler_id,
                    "type": "notifies",
                    "confidence": 0.9,
                    "provenance": "INFERRED",
                })
        self._notify_pending.clear()

        for role_name, vars_id in self._role_vars_pending:
            role_id = self._ensure_role(role_name)
            edges.append({
                "from": role_id,
                "to": vars_id,
                "type": "uses_vars",
                "confidence": 1.0,
                "provenance": "EXTRACTED",
            })
        self._role_vars_pending.clear()

        for group, vars_id in self._group_vars.items():
            for play_id, play_node in self._plays.items():
                hosts = play_node["labels"].get("hosts", "")
                if group == "all" or group in _hosts_tokens(hosts):
                    edges.append({
                        "from": vars_id,
                        "to": play_id,
                        "type": "uses_vars",
                        "confidence": 0.9,
                        "provenance": "INFERRED",
                    })
        self._group_vars.clear()

        for host, vars_id in self._host_vars.items():
            for play_id, play_node in self._plays.items():
                hosts = play_node["labels"].get("hosts", "")
                if host in _hosts_tokens(hosts):
                    edges.append({
                        "from": vars_id,
                        "to": play_id,
                        "type": "uses_vars",
                        "confidence": 0.9,
                        "provenance": "INFERRED",
                    })
        self._host_vars.clear()

        return edges

    def _resolve_notify(self, role_name: str | None, handler_name: str) -> list[str]:
        """Resolve a `notify` string to handler id(s) within `role_name`.

        Matches the handler's `name:` first; falls back to `listen:` topics
        (a topic can fan out to several handlers). No role scope (e.g. a
        notify outside any role) resolves to nothing.
        """
        if role_name is None:
            return []
        by_name = self._handlers.get((role_name, handler_name))
        if by_name is not None:
            return [by_name]
        return list(self._handler_listen.get((role_name, handler_name), []))

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
            hosts = _normalize_hosts(hosts_raw)
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
                    # Playbook-level tasks aren't scoped to a role, so any
                    # `notify` here has no role to resolve a handler within.
                    nodes_new, edges_new = self._extract_task_includes(
                        task, play_id, seen_ids, file_str, path.parent, role_name=None
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
                task, task_file_id, seen_ids, file_str, path.parent, role_name=role_name
            )
            nodes.extend(nodes_new)
            seen_ids.update(n["id"] for n in nodes_new)
            edges.extend(edges_new)

        return {"nodes": nodes, "edges": edges}

    # ── Handler file ──────────────────────────────────────────────────────────

    def _parse_handler_file(self, path: Path, handlers: list) -> dict[str, Any]:
        nodes: list[dict] = []
        edges: list[dict] = []
        file_str = str(path)
        role_name = self._role_name_from_path(path)
        if role_name:
            self._ensure_role(role_name, nodes)

        for handler in handlers:
            if not isinstance(handler, dict):
                continue
            name = handler.get("name")
            if not name:
                continue

            line = None
            try:
                line = handler.lc.line + 1
            except AttributeError:
                pass

            if role_name:
                handler_id = f"handler/{role_name}/{name}"
            else:
                # Standalone (non-role-scoped) handler file — path-qualified,
                # per the ID conventions (`handler/<rel_posix(path)>#<name>`).
                handler_id = qualified("handler", rel_posix(path, self._root), name)

            listen = handler.get("listen")
            handler_node = {
                "id": handler_id,
                "type": "handler",
                "kind": "ansible_handler",
                "name": name,
                "file": file_str,
                "line": line,
                "labels": {"listen": listen} if listen else {},
                "community_id": None,
            }
            nodes.append(handler_node)

            if role_name:
                self._handlers[(role_name, name)] = handler_id
                self._role_handler_pending.append((role_name, handler_id))
                for topic in listen if isinstance(listen, list) else [listen] if listen else []:
                    self._handler_listen.setdefault((role_name, str(topic)), []).append(handler_id)

        return {"nodes": nodes, "edges": edges}

    # ── Vars files ────────────────────────────────────────────────────────────

    def _parse_group_vars_file(self, path: Path) -> dict[str, Any]:
        group = self._group_or_host_name_from_path(path, "group_vars")
        if not group:
            return {"nodes": [], "edges": []}
        vars_id = f"vars/group/{group}"
        nodes = self._make_vars_node(vars_id, group, path, {"scope": "group"})
        self._group_vars[group] = vars_id
        return {"nodes": nodes, "edges": []}

    def _parse_host_vars_file(self, path: Path) -> dict[str, Any]:
        host = self._group_or_host_name_from_path(path, "host_vars")
        if not host:
            return {"nodes": [], "edges": []}
        vars_id = f"vars/host/{host}"
        nodes = self._make_vars_node(vars_id, host, path, {"scope": "host"})
        self._host_vars[host] = vars_id
        return {"nodes": nodes, "edges": []}

    def _parse_role_vars_file(self, path: Path, role_name: str, kind: str) -> dict[str, Any]:
        rel = rel_posix(path, self._root)
        vars_id = f"vars/{rel}"
        nodes = self._make_vars_node(
            vars_id, path.stem, path, {"scope": "role", "role": role_name, "kind": kind}
        )
        self._ensure_role(role_name, nodes)  # lazily emits the role node too
        self._role_vars_pending.append((role_name, vars_id))
        return {"nodes": nodes, "edges": []}

    def _make_vars_node(
        self, vars_id: str, name: str, path: Path, labels: dict[str, Any]
    ) -> list[dict]:
        """Register `vars_id` in `self._vars`, returning `[node]` the first
        time it's seen (so repeat references — e.g. a second file for the
        same group_vars group — don't re-emit a duplicate node)."""
        if vars_id in self._vars:
            return []
        node = {
            "id": vars_id,
            "type": "vars",
            "kind": "ansible_vars",
            "name": name,
            "file": str(path),
            "line": None,
            "labels": labels,
            "community_id": None,
        }
        self._vars[vars_id] = node
        return [node]

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
    def _role_vars_kind(path: Path) -> str | None:
        """`roles/<name>/defaults/...` -> "defaults", `roles/<name>/vars/...`
        -> "vars", else None."""
        parts = path.parts
        if "roles" not in parts:
            return None
        idx = parts.index("roles")
        if idx + 2 >= len(parts):
            return None
        kind = parts[idx + 2]
        return kind if kind in ("defaults", "vars") else None

    @staticmethod
    def _group_or_host_name_from_path(path: Path, segment: str) -> str | None:
        """`<segment>/<name>.yml` -> `<name>`; `<segment>/<name>/*.yml`
        (Ansible's directory form) -> `<name>` too."""
        parts = path.parts
        if segment not in parts:
            return None
        idx = parts.index(segment)
        remainder = parts[idx + 1 :]
        if not remainder:
            return None
        if len(remainder) == 1:
            return Path(remainder[0]).stem
        return remainder[0]

    @staticmethod
    def _role_name(entry: Any) -> str | None:
        if isinstance(entry, str):
            return entry
        if isinstance(entry, dict):
            return entry.get("role") or entry.get("name")
        return None

    _INCLUDE_EDGE_TYPES = {
        "include_tasks": "includes_tasks",
        "import_tasks": "imports_tasks",
    }

    def _extract_task_includes(
        self,
        task: Any,
        owner_id: str,
        seen_ids: set[str],
        file_str: str,
        task_dir: Path,
        role_name: str | None,
    ) -> tuple[list[dict], list[dict]]:
        """Record include_tasks/import_tasks/include_role/import_role/notify
        found in `task` as pending references (resolved in `finalize()`),
        recursing into `block`/`rescue`/`always` so nested directives are
        found too.

        `task_dir` is the directory of the file `task` was parsed from — the
        base for resolving `include_tasks`/`import_tasks` `ref` values, which
        Ansible resolves relative to the including file, not the repo root.

        `role_name` is the role this task belongs to (from the containing
        task file's path), or `None` for playbook-level tasks — it scopes
        `notify` resolution, since a handler is matched within the same role.

        No nodes/edges are emitted directly here: everything routes through
        `self._include_pending` / `self._include_role_pending` /
        `self._notify_pending` so a target's path-qualified id (or a
        notify's handler match) is only resolved once, in `finalize()`,
        after every real file has had a chance to register itself.
        """
        nodes: list[dict] = []
        edges: list[dict] = []
        if not isinstance(task, dict):
            return nodes, edges

        for inc_key, edge_type in self._INCLUDE_EDGE_TYPES.items():
            ref = task.get(inc_key)
            if not ref:
                continue
            if isinstance(ref, dict):
                ref = ref.get("file") or ref.get("name")
            if not ref:
                continue
            self._include_pending.append((owner_id, task_dir, str(ref), edge_type))

        for role_key in ("include_role", "import_role"):
            entry = task.get(role_key)
            if not entry:
                continue
            included_role_name = self._role_name(entry)
            if included_role_name:
                self._include_role_pending.append((owner_id, included_role_name))

        notify = task.get("notify")
        for handler_name in notify if isinstance(notify, list) else [notify] if notify else []:
            if handler_name:
                self._notify_pending.append((owner_id, str(handler_name), role_name))

        # block/rescue/always each hold a nested task list; recurse so an
        # include/notify buried in any of them is still found. Nested tasks
        # stay attributed to the same owner (the containing task_file/play)
        # and the same role scope — this schema doesn't model individual
        # task nodes.
        for block_key in ("block", "rescue", "always"):
            nested = task.get(block_key)
            if not isinstance(nested, list):
                continue
            for sub_task in nested:
                nodes_new, edges_new = self._extract_task_includes(
                    sub_task, owner_id, seen_ids, file_str, task_dir, role_name
                )
                nodes.extend(nodes_new)
                edges.extend(edges_new)

        return nodes, edges
