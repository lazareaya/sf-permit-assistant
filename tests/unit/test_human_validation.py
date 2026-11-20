"""send_submission must never succeed before a human approval."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import db, tools
from app.approvals import router

DRAFT = (
    "# Dossier\n" + "Pièces à fournir selon https://example.test/kitchen-remodel. " * 10
)


def _client():
    api = FastAPI()
    api.include_router(router)
    return TestClient(api)


def test_draft_is_pending_and_not_sent():
    out = tools.create_submission_draft(1, DRAFT)
    assert out["status"] == "pending_approval"
    assert db.get_submission(out["submission_id"])["sent_at"] is None


def test_one_pending_draft_per_project():
    a = tools.create_submission_draft(1, DRAFT)
    b = tools.create_submission_draft(1, DRAFT + " v2")
    assert b["updated_existing"] and a["submission_id"] == b["submission_id"]


def test_draft_too_short_rejected():
    assert tools.create_submission_draft(1, "trop court")["error"] == "INVALID_INPUT"


def test_send_refused_when_pending():
    sid = tools.create_submission_draft(1, DRAFT)["submission_id"]
    out = tools.send_submission(sid)
    assert out["error"] == "NOT_APPROVED"
    assert db.get_submission(sid)["status"] == "pending_approval"


def test_send_refused_when_rejected_or_already_sent():
    assert (
        tools.send_submission(3)["error"] == "NOT_APPROVED"
    )  # seed #3 is already sent
    sid = tools.create_submission_draft(2, DRAFT)["submission_id"]
    db.decide_submission(sid, approve=False, reviewer="x")
    assert tools.send_submission(sid)["error"] == "NOT_APPROVED"


def test_approve_in_ui_then_send():
    sid = tools.create_submission_draft(1, DRAFT)["submission_id"]
    c = _client()
    assert sid in [
        s["submission_id"] if "submission_id" in s else s["id"]
        for s in c.get("/submissions?status=pending_approval").json()
    ]
    assert c.post(f"/submissions/{sid}/send").status_code == 409  # not approved yet
    assert (
        c.post(f"/submissions/{sid}/approve", json={"reviewer": "alice"}).json()[
            "status"
        ]
        == "approved"
    )
    assert c.post(f"/submissions/{sid}/approve").status_code == 409  # single decision
    assert tools.send_submission(sid)["status"] == "sent"
    assert db.get_submission(sid)["sent_at"]


def test_reject_in_ui():
    sid = tools.create_submission_draft(1, DRAFT)["submission_id"]
    assert _client().post(f"/submissions/{sid}/reject").json()["status"] == "rejected"


def test_unknown_submission():
    assert tools.send_submission(999)["error"] == "SUBMISSION_NOT_FOUND"
    assert _client().post("/submissions/999/approve").status_code == 404
