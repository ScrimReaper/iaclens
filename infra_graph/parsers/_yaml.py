"""YAML loading shared by every parser: fast, with line numbers.

The round-trip loader (`YAML()`) keeps comments, quotes, and formatting we
never use. `typ="safe"` is 5-8x faster when `ruamel.yaml.clib` is installed
(nixpkgs ships it) and still ~25% faster in pure Python. The parsers need
only plain data plus the start line of a mapping, so a dict subclass records
that line while constructing.

Any text the fast loader rejects but the round-trip loader accepts (unknown
tags such as Ansible's `!vault`, a stricter C scanner) is re-parsed with the
round-trip loader, so the set of parseable files is unchanged.
"""

from __future__ import annotations

from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.constructor import SafeConstructor
from ruamel.yaml.nodes import MappingNode, SequenceNode


class LineDict(dict):
    """A plain dict that remembers the 0-based line its mapping started on."""

    __slots__ = ("lc_line",)


class _LineConstructor(SafeConstructor):
    def construct_yaml_map(self, node: Any):  # type: ignore[override]
        data = LineDict()
        data.lc_line = node.start_mark.line
        yield data
        data.update(self.construct_mapping(node))

    def construct_undefined(self, node: Any) -> Any:  # type: ignore[override]
        # Unknown tags (`!vault`, `!reference`, ...): keep the plain value.
        if isinstance(node, MappingNode):
            data = LineDict()
            data.lc_line = node.start_mark.line
            data.update(self.construct_mapping(node, deep=True))
            return data
        if isinstance(node, SequenceNode):
            return self.construct_sequence(node, deep=True)
        return node.value


_LineConstructor.add_constructor("tag:yaml.org,2002:map", _LineConstructor.construct_yaml_map)
_LineConstructor.add_constructor(None, _LineConstructor.construct_undefined)

_fast = YAML(typ="safe")
_fast.Constructor = _LineConstructor

_round_trip = YAML()
_round_trip.preserve_quotes = True


def load_all(text: str) -> list[Any]:
    """Parse every document in `text`. Raises if neither loader accepts it."""
    try:
        return list(_fast.load_all(text))
    except Exception:
        return list(_round_trip.load_all(text))


def load(text: str) -> Any:
    """Parse a single-document `text` (raises on multi-document input)."""
    try:
        return _fast.load(text)
    except Exception:
        return _round_trip.load(text)


def line_of(obj: Any) -> int | None:
    """1-based start line of a parsed mapping, from either loader; None if unknown."""
    line = getattr(obj, "lc_line", None)
    if line is None:
        lc = getattr(obj, "lc", None)
        line = getattr(lc, "line", None)
    return line + 1 if isinstance(line, int) else None
