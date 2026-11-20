import sqlite3

import pytest

from app import db, tools


def test_twenty_projects_at_real_addresses():
    projects = tools.list_projects()["projects"]
    assert len(projects) == 20
    assert {p["work_type"] for p in projects} == {
        "kitchen_remodel",
        "bathroom_remodel",
        "adu",
        "reroofing",
        "solar",
        "windows",
    }


def test_get_project_with_submissions():
    p = tools.get_project(5)
    assert (
        p["address"] == "1900 15th Ave"
        and p["submissions"][0]["status"] == "pending_approval"
    )


def test_unknown_project():
    assert tools.get_project(999)["error"] == "PROJECT_NOT_FOUND"


def test_invalid_project_id():
    assert tools.get_project(0)["error"] == "INVALID_INPUT"


def test_read_connection_is_read_only():
    with db.read_conn() as con, pytest.raises(sqlite3.OperationalError):
        con.execute("UPDATE projects SET status='filed'")
