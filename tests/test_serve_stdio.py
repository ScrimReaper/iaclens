"""Start the real MCP server over stdio and talk to it with the mcp client.

The unit tests never started the server, so an incompatible `mcp` release
(2.x removed the low-level decorator API) went unnoticed: `iaclens serve`
crashed on startup while every test stayed green. This test runs against
whichever `mcp` is installed.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

mcp = pytest.importorskip("mcp")
from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402


def _params(args: list[str]) -> StdioServerParameters:
    env = dict(os.environ)
    env["IACLENS_NO_WATCH"] = "1"
    return StdioServerParameters(
        command=sys.executable,
        args=["-c", "from infra_graph.cli import cli; cli()", "serve", *args],
        env=env,
    )


def _ns(root: Path, name: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{name}.yaml").write_text(
        f"apiVersion: v1\nkind: Namespace\nmetadata:\n  name: {name}\n"
    )


async def _tool(session: ClientSession, name: str, args: dict) -> dict:
    result = await session.call_tool(name, args)
    return json.loads(result.content[0].text)


async def _single_root(root: Path) -> dict:
    async with stdio_client(_params(["--path", str(root)])) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = sorted(t.name for t in tools.tools)
            ctx = await _tool(session, "get_minimal_context", {})
            found = await _tool(session, "search_resources", {"query": "alpha"})
            return {"tools": names, "nodes": ctx["nodes"], "found": found["total_matches"]}


async def _multi_root(a: Path, b: Path) -> dict:
    async with stdio_client(_params(["--path", str(a), "--path", str(b)])) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            found = await _tool(session, "search_resources", {"query": "namespace"})
            ids = sorted(r["id"] for r in found["results"])
            _ns(b, "gamma")
            rebuilt = await _tool(session, "build_or_update_graph", {"path": str(b)})
            after = await _tool(session, "search_resources", {"query": "gamma"})
            return {"ids": ids, "federated": rebuilt.get("federated"), "gamma": after["total_matches"]}


def test_single_root_server_answers_over_stdio(tmp_path):
    _ns(tmp_path, "alpha")
    out = asyncio.run(_single_root(tmp_path))
    assert len(out["tools"]) == 10
    assert "get_blast_radius" in out["tools"]
    assert out["nodes"] == 1
    assert out["found"] == 1


def test_multi_root_server_federates_and_rebuilds_over_stdio(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    _ns(a, "alpha")
    _ns(b, "beta")
    out = asyncio.run(_multi_root(a, b))
    assert out["ids"] == ["Namespace/default/alpha", "Namespace/default/beta"]
    assert out["federated"] is True
    assert out["gamma"] == 1
