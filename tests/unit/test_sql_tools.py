import sqlite3

import pytest

from app import db, tools


def test_card_status_known_card():
    out = tools.get_card_status("CARD-00001")
    assert out["card_id"] == "CARD-00001"
    assert out["status"] in {"active", "blocked"}
    assert "customer_name" in out


def test_card_status_unknown_card():
    assert tools.get_card_status("CARD-99999")["error"] == "CARD_NOT_FOUND"


@pytest.mark.parametrize(
    "bad", ["42", "CARD-1", "card-00001", "CARD-00001; DROP TABLE cards"]
)
def test_invalid_card_id_rejected_by_pydantic(bad):
    assert tools.get_card_status(bad)["error"] == "INVALID_INPUT"


def test_history_returns_recent_tx_and_stats():
    out = tools.get_transaction_history("CARD-00185", limit=5)
    assert len(out["transactions"]) == 5
    assert out["stats"]["n_tx"] > 5
    ts = [t["ts"] for t in out["transactions"]]
    assert ts == sorted(ts, reverse=True)


def test_history_never_leaks_ground_truth_label():
    out = tools.get_transaction_history("CARD-00185", limit=100)
    assert all("label_is_fraud" not in t for t in out["transactions"])


def test_history_limit_validated():
    assert (
        tools.get_transaction_history("CARD-00001", limit=1000)["error"]
        == "INVALID_INPUT"
    )


def test_read_connection_is_read_only():
    with db.read_conn() as con, pytest.raises(sqlite3.OperationalError):
        con.execute("UPDATE cards SET status='blocked'")
