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
            "PROJECTS_DB_PATH": str(db_path),
            "DATASF_URL": "http://127.0.0.1:9/resource.json",
            "DATASF_CACHE": "off",
        },  # DataSF "down"
    )
    async with stdio_client(params) as (r, w), ClientSession(r, w) as session:
        await session.initialize()
        return await fn(session)


def _payload(result):
    return json.loads(result.content[0].text)


@pytest.mark.asyncio
async def test_mcp_exposes_the_five_tools(temp_db):
    tools = await _with_session(lambda s: s.list_tools(), temp_db)
    assert {t.name for t in tools.tools} == {
        "search_permits",
        "list_projects",
        "get_project",
        "create_submission_draft",
        "send_submission",
    }


@pytest.mark.asyncio
async def test_mcp_read_tools(temp_db):
    async def run(s):
        return await s.call_tool("list_projects", {}), await s.call_tool(
            "get_project", {"project_id": 999}
        )

    projects, missing = await _with_session(run, temp_db)
    assert len(_payload(projects)["projects"]) == 20
    assert _payload(missing)["error"] == "PROJECT_NOT_FOUND"


@pytest.mark.asyncio
async def test_mcp_search_permits_reports_outage(temp_db):
    res = await _with_session(
        lambda s: s.call_tool("search_permits", {"address": "781 20th Ave"}), temp_db
    )
    assert _payload(res)["error"] == "DATASF_UNAVAILABLE"


@pytest.mark.asyncio
async def test_mcp_send_refused_without_approval(temp_db):
    res = await _with_session(
        lambda s: s.call_tool("send_submission", {"submission_id": 1}), temp_db
    )
    assert _payload(res)["error"] == "NOT_APPROVED"
