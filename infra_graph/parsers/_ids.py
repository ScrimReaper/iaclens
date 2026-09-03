"""Shared helpers for collision-free, path-qualified node IDs."""

from pathlib import Path


def rel_posix(path: Path, root: Path) -> str:
    """`path` relative to `root` as a POSIX string; falls back to the file name
    if `path` is not under `root`."""
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.name


def qualified(prefix: str, rel: str, name: str) -> str:
    """Node ID `"<prefix>/<rel>#<name>"` — `rel` is a repo-relative path
    (file or dir), `name` the local element name; `#` separates location from name."""
    return f"{prefix}/{rel}#{name}"
