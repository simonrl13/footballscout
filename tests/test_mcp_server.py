"""MCP server: tool list and schemas without a DB; real calls (in-process and over stdio) when the DB is up."""
import asyncio
import json
import os
import sys

import pytest

from scout.agent import tools
from scout.data.manifest import ROOT
from scout.mcp_server import server


def run(coro):
    return asyncio.run(coro)


def test_same_four_tools_all_read_only_with_limits_in_the_schema():
    listed = {t.name: t for t in run(server.list_tools())}
    assert set(listed) == set(tools.TOOLS)
    assert all(t.annotations.read_only_hint and not t.annotations.destructive_hint for t in listed.values())
    props = listed["search_players"].input_schema["properties"]
    assert json.dumps(props["limit"]).count('"maximum": 20') == 1
    assert listed["compare_players"].input_schema["required"] == ["player_ids"]


@pytest.mark.parametrize("name,args", [
    ("search_players", {"limit": 99}),
    ("search_players", {"league": "XX1"}),
    ("predict_value_change", {"player_id": 0}),
    ("compare_players", {"player_ids": [1]}),
])
def test_invalid_arguments_are_rejected_before_any_query(monkeypatch, name, args):
    monkeypatch.setattr(tools, "connect", lambda: pytest.fail("connected despite invalid input"))
    with pytest.raises(Exception, match="validation error"):
        run(server.call_tool(name, args))


def _db_ready() -> bool:
    try:
        with tools.connect() as c:
            return c.execute("SELECT count(*) AS n FROM demo_players").fetchone()["n"] > 0
    except Exception:
        return False


@pytest.mark.skipif(not _db_ready(), reason="database or demo_players not available")
def test_search_in_process():
    out = run(server.call_tool("search_players", {"name": "yamal", "limit": 3}))
    assert "Lamine Yamal" in out.content[0].text


@pytest.mark.skipif(not _db_ready(), reason="database or demo_players not available")
def test_stdio_round_trip():
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    async def go():
        params = StdioServerParameters(command=sys.executable, args=["-m", "scout.mcp_server"], cwd=ROOT,
                                       env={**os.environ})
        async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            names = {t.name for t in (await session.list_tools()).tools}
            res = await session.call_tool("predict_value_change", {"player_id": 132098})
            return names, res
    names, res = run(go())
    assert names == set(tools.TOOLS) and not res.is_error
    assert json.loads(res.content[0].text)["forecast"]["interval_80_pct"]["low"] < 0
