"""block_card must never execute directly: only a human approval does."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import db, tools
from app.approvals import router

CARD = "CARD-00185"
JUSTIF = "Score 0.99 sur la transaction, 3 pays étrangers en 2 heures."


def _client():
    api = FastAPI()
    api.include_router(router)
    return TestClient(api)


def test_block_card_only_creates_pending_request():
    out = tools.block_card(CARD, JUSTIF, "PROC-01", tx_id=100541)
    assert out["status"] == "pending_approval"
    assert db.get_card_status(CARD)["status"] == "active"  # NOT blocked
    assert db.list_actions("pending_approval")[0]["card_id"] == CARD


def test_block_card_is_idempotent_while_pending():
    first = tools.block_card(CARD, JUSTIF, "PROC-01")
    second = tools.block_card(CARD, JUSTIF, "PROC-01")
    assert second["duplicate"] is True and second["action_id"] == first["action_id"]


def test_block_card_requires_known_procedure():
    assert tools.block_card(CARD, JUSTIF, "PROC-99")["error"] == "UNKNOWN_PROCEDURE"


def test_block_card_refuses_unknown_card():
    assert (
        tools.block_card("CARD-99999", JUSTIF, "PROC-01")["error"] == "CARD_NOT_FOUND"
    )


def test_block_card_refuses_already_blocked_card():
    assert (
        tools.block_card("CARD-00300", JUSTIF, "PROC-01")["error"] == "ALREADY_BLOCKED"
    )


def test_human_approval_executes_the_block():
    action_id = tools.block_card(CARD, JUSTIF, "PROC-01")["action_id"]
    client = _client()
    assert [
        a["action_id"] for a in client.get("/actions?status=pending_approval").json()
    ] == [action_id]
    r = client.post(f"/actions/{action_id}/approve", json={"reviewer": "alice"})
    assert r.status_code == 200 and r.json()["status"] == "executed"
    assert db.get_card_status(CARD)["status"] == "blocked"
    assert (
        client.post(f"/actions/{action_id}/approve").status_code == 409
    )  # no double decision


def test_human_rejection_leaves_card_active():
    action_id = tools.block_card(CARD, JUSTIF, "PROC-01")["action_id"]
    r = _client().post(f"/actions/{action_id}/reject", json={"reviewer": "bob"})
    assert r.json()["status"] == "rejected"
    assert db.get_card_status(CARD)["status"] == "active"
