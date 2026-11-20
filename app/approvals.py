"""Human-in-the-loop API: the analyst approves or rejects pending actions.

These routes are added to the agent's FastAPI server but are **not** tools:
the agent can only *request* an action (``block_card`` -> pending_approval);
executing it requires a human call to ``POST /actions/{id}/approve``.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app import db

router = APIRouter(prefix="/actions", tags=["human-in-the-loop"])


class Decision(BaseModel):
    reviewer: str = Field("analyste", min_length=2, max_length=80)


@router.get("")
def list_actions(
    status: Literal["pending_approval", "executed", "rejected"] | None = None,
) -> list[dict[str, Any]]:
    return db.list_actions(status)


def _decide(action_id: int, approve: bool, decision: Decision) -> dict[str, Any]:
    try:
        return db.decide_action(action_id, approve=approve, reviewer=decision.reviewer)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{action_id}/approve")
def approve(action_id: int, decision: Decision | None = None) -> dict[str, Any]:
    return _decide(action_id, True, decision or Decision())


@router.post("/{action_id}/reject")
def reject(action_id: int, decision: Decision | None = None) -> dict[str, Any]:
    return _decide(action_id, False, decision or Decision())
