"""Human-in-the-loop API: an architect approves, rejects and sends drafts.

These routes live on the agent's FastAPI server but are **not** tools: the
agent can only create drafts (``pending_approval``). Approving requires a human
call to ``POST /submissions/{id}/approve``; sending is refused unless approved.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app import db

router = APIRouter(prefix="/submissions", tags=["human-in-the-loop"])


class Decision(BaseModel):
    reviewer: str = Field("architecte", min_length=2, max_length=80)


@router.get("")
def list_submissions(
    status: Literal["pending_approval", "approved", "rejected", "sent"] | None = None,
) -> list[dict[str, Any]]:
    return db.list_submissions(status)


def _decide(submission_id: int, approve: bool, decision: Decision) -> dict[str, Any]:
    try:
        return db.decide_submission(
            submission_id, approve=approve, reviewer=decision.reviewer
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{submission_id}/approve")
def approve(submission_id: int, decision: Decision | None = None) -> dict[str, Any]:
    return _decide(submission_id, True, decision or Decision())


@router.post("/{submission_id}/reject")
def reject(submission_id: int, decision: Decision | None = None) -> dict[str, Any]:
    return _decide(submission_id, False, decision or Decision())


@router.post("/{submission_id}/send")
def send(submission_id: int) -> dict[str, Any]:
    try:
        return db.send_submission(submission_id)
    except db.SubmissionNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail=f"submission {submission_id} not found"
        ) from exc
    except db.NotApprovedError as exc:
        raise HTTPException(
            status_code=409, detail=f"submission is {exc}, not approved"
        ) from exc
