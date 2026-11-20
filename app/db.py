"""SQL access to the firm's projects database (SQLite).

Reads use a **read-only** connection (``mode=ro``). Writes are limited to:
* ``create_submission_draft`` -> status ``pending_approval`` (agent);
* ``decide_submission`` -> ``approved`` / ``rejected`` (human only, via the API);
* ``send_submission`` -> ``sent``, and only from ``approved``.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app import config


class ProjectNotFoundError(LookupError):
    pass


class SubmissionNotFoundError(LookupError):
    pass


class NotApprovedError(PermissionError):
    pass


def _db_path() -> Path:
    return Path(config.PROJECTS_DB_PATH)


@contextmanager
def read_conn():
    con = sqlite3.connect(f"file:{_db_path()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        yield con
    finally:
        con.close()


@contextmanager
def write_conn():
    con = sqlite3.connect(_db_path())
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


# --------------------------------------------------------------------- reads
def project_exists(project_id: int) -> bool:
    with read_conn() as con:
        return (
            con.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone()
            is not None
        )


def list_projects() -> list[dict[str, Any]]:
    with read_conn() as con:
        rows = con.execute(
            "SELECT id, client, address, work_type, status FROM projects ORDER BY id"
        ).fetchall()
    return [dict(r) for r in rows]


def get_project(project_id: int) -> dict[str, Any]:
    with read_conn() as con:
        row = con.execute(
            "SELECT * FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        if row is None:
            raise ProjectNotFoundError(project_id)
        subs = con.execute(
            "SELECT id, status, created_at, sent_at FROM submissions WHERE project_id = ? ORDER BY id DESC",
            (project_id,),
        ).fetchall()
    return {**dict(row), "submissions": [dict(s) for s in subs]}


def get_submission(submission_id: int) -> dict[str, Any]:
    with read_conn() as con:
        row = con.execute(
            "SELECT * FROM submissions WHERE id = ?", (submission_id,)
        ).fetchone()
    if row is None:
        raise SubmissionNotFoundError(submission_id)
    return dict(row)


def list_submissions(status: str | None = None) -> list[dict[str, Any]]:
    sql = (
        "SELECT s.*, p.address, p.client, p.work_type FROM submissions s "
        "JOIN projects p ON p.id = s.project_id"
    )
    with read_conn() as con:
        if status:
            rows = con.execute(
                sql + " WHERE s.status = ? ORDER BY s.id DESC", (status,)
            ).fetchall()
        else:
            rows = con.execute(sql + " ORDER BY s.id DESC").fetchall()
    return [dict(r) for r in rows]


# -------------------------------------------------------------------- writes
def create_submission_draft(project_id: int, content: str) -> dict[str, Any]:
    with write_conn() as con:
        if (
            con.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone()
            is None
        ):
            raise ProjectNotFoundError(project_id)
        pending = con.execute(
            "SELECT id FROM submissions WHERE project_id = ? AND status = 'pending_approval'",
            (project_id,),
        ).fetchone()
        if pending:  # one pending draft per project: update it instead of piling up
            con.execute(
                "UPDATE submissions SET draft = ?, created_at = ? WHERE id = ?",
                (content, _now(), pending["id"]),
            )
            return {
                "submission_id": pending["id"],
                "status": "pending_approval",
                "updated_existing": True,
            }
        cur = con.execute(
            "INSERT INTO submissions (project_id, draft, status, created_at) VALUES (?, ?, 'pending_approval', ?)",
            (project_id, content, _now()),
        )
        return {
            "submission_id": cur.lastrowid,
            "status": "pending_approval",
            "updated_existing": False,
        }


def decide_submission(
    submission_id: int, approve: bool, reviewer: str
) -> dict[str, Any]:
    """Human decision on a pending draft."""
    with write_conn() as con:
        row = con.execute(
            "SELECT * FROM submissions WHERE id = ?", (submission_id,)
        ).fetchone()
        if row is None:
            raise SubmissionNotFoundError(submission_id)
        if row["status"] != "pending_approval":
            raise ValueError(f"submission {submission_id} is already {row['status']}")
        status = "approved" if approve else "rejected"
        con.execute(
            "UPDATE submissions SET status = ?, decided_by = ?, decided_at = ? WHERE id = ?",
            (status, reviewer, _now(), submission_id),
        )
    return {"submission_id": submission_id, "status": status}


def send_submission(submission_id: int) -> dict[str, Any]:
    """Send (simulated) an APPROVED submission. Any other status is refused."""
    with write_conn() as con:
        row = con.execute(
            "SELECT * FROM submissions WHERE id = ?", (submission_id,)
        ).fetchone()
        if row is None:
            raise SubmissionNotFoundError(submission_id)
        if row["status"] != "approved":
            raise NotApprovedError(row["status"])
        sent_at = _now()
        con.execute(
            "UPDATE submissions SET status = 'sent', sent_at = ? WHERE id = ?",
            (sent_at, submission_id),
        )
    return {"submission_id": submission_id, "status": "sent", "sent_at": sent_at}
