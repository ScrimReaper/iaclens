"""Shell completion for the iaclens CLI.

Two pieces:

- ``emit_completion_script`` prints the shell hook that a user evaluates to
  turn on completion (bash, zsh, or fish).
- ``complete_node_ids`` is a Click ``shell_complete`` callback that suggests
  graph node ids for node arguments. Completion runs on every <Tab>, so it
  must be fast and must never raise: any failure (no graph built yet, an
  unreadable file) yields no suggestions instead of an error.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from click.shell_completion import CompletionItem, get_completion_class

SUPPORTED_SHELLS = ("bash", "zsh", "fish")

_COMPLETE_VAR = "_IACLENS_COMPLETE"
_MAX_SUGGESTIONS = 50


def emit_completion_script(shell: str, prog_name: str = "iaclens") -> str:
    """Return the completion hook script for ``shell``.

    Raises ``ValueError`` for a shell Click cannot complete.
    """
    if shell not in SUPPORTED_SHELLS:
        raise ValueError(
            f"Unsupported shell: {shell!r}. Choose one of {', '.join(SUPPORTED_SHELLS)}."
        )
    comp_cls = get_completion_class(shell)
    if comp_cls is None:  # pragma: no cover - registry always has our shells
        raise ValueError(f"Shell {shell!r} has no Click completion class.")

    from .cli import cli

    completer = comp_cls(cli, {}, prog_name, _COMPLETE_VAR)
    return completer.source()


def _project_root_from_ctx(ctx: Any) -> Path:
    params = getattr(ctx, "params", {}) or {}
    # `path` is the common option name; the `path` command uses `project_path`.
    raw = params.get("path") or params.get("project_path") or "."
    return Path(raw).resolve()


def _load_node_ids(project_root: Path) -> list[str]:
    """Load node ids from a built graph without side effects.

    Reads ``iaclens-out/graph.toon`` (or ``graph.json``) directly, so it does
    not create the output directory the way ``GraphBuilder`` does.
    """
    out_dir = project_root / "iaclens-out"
    toon_path = out_dir / "graph.toon"
    json_path = out_dir / "graph.json"

    if toon_path.exists():
        from .graph import toon

        graph, _ = toon.load_graph(toon_path)
        return list(graph.nodes())

    if json_path.exists():
        import json

        data = json.loads(json_path.read_text())
        return [n["id"] for n in data.get("nodes", []) if "id" in n]

    return []


def complete_node_ids(ctx: Any, param: Any, incomplete: str) -> list[CompletionItem]:
    """Suggest graph node ids whose id contains ``incomplete`` (case-insensitive)."""
    try:
        node_ids = _load_node_ids(_project_root_from_ctx(ctx))
    except Exception:
        return []

    needle = incomplete.lower()
    out: list[CompletionItem] = []
    for nid in node_ids:
        if needle in nid.lower():
            out.append(CompletionItem(nid))
            if len(out) >= _MAX_SUGGESTIONS:
                break
    return out
