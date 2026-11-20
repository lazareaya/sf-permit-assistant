"""Talk to the real MCP server over stdio, as the agent does."""

import json
import os
import sys

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from app import config


async def _with_session(fn, db_path):
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "mcp_server.server"],
        cwd=str(config.ROOT),
        env={
            **os.environ,
            "PYTHONPATH": str(config.ROOT),
            "BANK_DB_PATH": str(db_path),
            "FRAUD_API_URL": "http://127.0.0.1:9",
        },  # nothing listens there
    )
    async with stdio_client(params) as (r, w), ClientSession(r, w) as session:
        await session.initialize()
        return await fn(session)


def _payload(result):
    return json.loads(result.content[0].text)


@pytest.mark.asyncio
async def test_mcp_exposes_the_four_tools(temp_db):
    tools = await _with_session(lambda s: s.list_tools(), temp_db)
    assert {t.name for t in tools.tools} == {
        "score_transaction",
        "get_transaction_history",
        "get_card_status",
        "block_card",
    }


@pytest.mark.asyncio
async def test_mcp_history_and_status(temp_db):
    async def run(s):
        return (
            await s.call_tool(
                "get_transaction_history", {"card_id": "CARD-00185", "limit": 3}
            ),
            await s.call_tool("get_card_status", {"card_id": "CARD-99999"}),
        )

    hist, status = await _with_session(run, temp_db)
    assert len(_payload(hist)["transactions"]) == 3
    assert _payload(status)["error"] == "CARD_NOT_FOUND"


@pytest.mark.asyncio
async def test_mcp_score_reports_api_outage(temp_db):
    res = await _with_session(
        lambda s: s.call_tool("score_transaction", {"tx_id": 100541}), temp_db
    )
    assert _payload(res)["error"] == "FRAUD_API_UNAVAILABLE"


@pytest.mark.asyncio
async def test_mcp_block_card_is_pending_only(temp_db):
    args = {
        "card_id": "CARD-00185",
        "justification": "score 0.99 et 3 pays étrangers",
        "procedure_id": "PROC-01",
    }
    res = await _with_session(lambda s: s.call_tool("block_card", args), temp_db)
    assert _payload(res)["status"] == "pending_approval"
    from app import db

    assert db.get_card_status("CARD-00185")["status"] == "active"
