"""SQL access to the bank database (SQLite).

Reads go through a **read-only** connection (``mode=ro``), so a tool that only
needs to look at data physically cannot modify it. The only writes are:

* ``create_pending_action``: the agent *requests* an action (status
  ``pending_approval``), it never executes it;
* ``decide_action``: called by the human reviewer from the UI/API, never
  exposed to the agent.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app import config

FEATURE_COLS = ["time_raw", "amount"] + [f"V{i}" for i in range(1, 29)]


class CardNotFoundError(LookupError):
    pass


class TransactionNotFoundError(LookupError):
    pass


def _db_path() -> Path:
    return Path(config.BANK_DB_PATH)


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
def card_exists(card_id: str) -> bool:
    with read_conn() as con:
        return (
            con.execute("SELECT 1 FROM cards WHERE card_id = ?", (card_id,)).fetchone()
            is not None
        )


def get_card_status(card_id: str) -> dict[str, Any]:
    with read_conn() as con:
        row = con.execute(
            "SELECT card_id, customer_name, status, daily_limit, opened_at FROM cards WHERE card_id = ?",
            (card_id,),
        ).fetchone()
        if row is None:
            raise CardNotFoundError(card_id)
        pending = con.execute(
            "SELECT action_id, action_type, status, created_at FROM actions "
            "WHERE card_id = ? ORDER BY action_id DESC LIMIT 5",
            (card_id,),
        ).fetchall()
    return {**dict(row), "recent_actions": [dict(p) for p in pending]}


def get_transaction_history(card_id: str, limit: int = 20) -> dict[str, Any]:
    """Latest transactions of a card + aggregate stats (no ground-truth label)."""
    with read_conn() as con:
        if (
            con.execute("SELECT 1 FROM cards WHERE card_id = ?", (card_id,)).fetchone()
            is None
        ):
            raise CardNotFoundError(card_id)
        rows = con.execute(
            "SELECT tx_id, ts, amount, merchant_category, country FROM transactions "
            "WHERE card_id = ? ORDER BY ts DESC LIMIT ?",
            (card_id, limit),
        ).fetchall()
        stats = con.execute(
            "SELECT COUNT(*) AS n_tx, ROUND(AVG(amount), 2) AS avg_amount, "
            "ROUND(MAX(amount), 2) AS max_amount, "
            "SUM(CASE WHEN country <> 'FR' THEN 1 ELSE 0 END) AS n_foreign "
            "FROM transactions WHERE card_id = ?",
            (card_id,),
        ).fetchone()
    return {
        "card_id": card_id,
        "stats": dict(stats),
        "transactions": [dict(r) for r in rows],
    }


def get_transaction(tx_id: int) -> dict[str, Any]:
    with read_conn() as con:
        row = con.execute(
            f"SELECT tx_id, card_id, ts, amount, merchant_category, country, {', '.join(FEATURE_COLS)} "
            "FROM transactions WHERE tx_id = ?",
            (tx_id,),
        ).fetchone()
    if row is None:
        raise TransactionNotFoundError(tx_id)
    return dict(row)


def fraud_api_payload(tx: dict[str, Any]) -> dict[str, float]:
    """Map a DB row to the Project 2 API contract (Time, Amount, V1..V28)."""
    payload = {"Time": float(tx["time_raw"]), "Amount": float(tx["amount"])}
    payload.update({f"V{i}": float(tx[f"V{i}"]) for i in range(1, 29)})
    return payload


def list_actions(status: str | None = None) -> list[dict[str, Any]]:
    with read_conn() as con:
        if status:
            rows = con.execute(
                "SELECT * FROM actions WHERE status = ? ORDER BY action_id DESC",
                (status,),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM actions ORDER BY action_id DESC"
            ).fetchall()
    return [dict(r) for r in rows]


# -------------------------------------------------------------------- writes
def create_pending_action(
    card_id: str,
    justification: str,
    procedure_id: str,
    tx_id: int | None = None,
    action_type: str = "block_card",
    requested_by: str = "fraud_analyst_agent",
) -> dict[str, Any]:
    """Record a *request* for a risky action. Nothing is executed here."""
    with write_conn() as con:
        if (
            con.execute("SELECT 1 FROM cards WHERE card_id = ?", (card_id,)).fetchone()
            is None
        ):
            raise CardNotFoundError(card_id)
        existing = con.execute(
            "SELECT action_id FROM actions WHERE card_id = ? AND action_type = ? AND status = 'pending_approval'",
            (card_id, action_type),
        ).fetchone()
        if existing:
            return {
                "action_id": existing["action_id"],
                "status": "pending_approval",
                "duplicate": True,
            }
        cur = con.execute(
            "INSERT INTO actions (card_id, tx_id, action_type, justification, procedure_id, status, requested_by, created_at) "
            "VALUES (?, ?, ?, ?, ?, 'pending_approval', ?, ?)",
            (
                card_id,
                tx_id,
                action_type,
                justification,
                procedure_id,
                requested_by,
                _now(),
            ),
        )
        return {
            "action_id": cur.lastrowid,
            "status": "pending_approval",
            "duplicate": False,
        }


def decide_action(action_id: int, approve: bool, reviewer: str) -> dict[str, Any]:
    """Human decision. Only an approval actually executes the action."""
    with write_conn() as con:
        row = con.execute(
            "SELECT * FROM actions WHERE action_id = ?", (action_id,)
        ).fetchone()
        if row is None:
            raise LookupError(f"action {action_id} not found")
        if row["status"] != "pending_approval":
            raise ValueError(f"action {action_id} already {row['status']}")
        new_status = "executed" if approve else "rejected"
        if approve and row["action_type"] == "block_card":
            con.execute(
                "UPDATE cards SET status = 'blocked' WHERE card_id = ?",
                (row["card_id"],),
            )
        con.execute(
            "UPDATE actions SET status = ?, decided_by = ?, decided_at = ? WHERE action_id = ?",
            (new_status, reviewer, _now(), action_id),
        )
    return {"action_id": action_id, "status": new_status, "card_id": row["card_id"]}
