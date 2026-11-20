"""Pydantic models validating every tool input (guardrail: input validation)."""

from __future__ import annotations

from pydantic import BaseModel, Field

CARD_ID_PATTERN = r"^CARD-\d{5}$"


class CardArgs(BaseModel):
    card_id: str = Field(..., pattern=CARD_ID_PATTERN, description="ex: CARD-00042")


class HistoryArgs(CardArgs):
    limit: int = Field(20, ge=1, le=100)


class ScoreArgs(BaseModel):
    tx_id: int = Field(..., ge=100001, le=999999)


class BlockCardArgs(CardArgs):
    tx_id: int | None = Field(None, ge=100001, le=999999)
    justification: str = Field(..., min_length=20, max_length=2000)
    procedure_id: str = Field(..., pattern=r"^PROC-\d{2}$")


class SearchArgs(BaseModel):
    question: str = Field(..., min_length=3, max_length=500)


class SkillArgs(BaseModel):
    skill_name: str = Field(..., min_length=3, max_length=40)


TOOL_ARG_MODELS: dict[str, type[BaseModel]] = {
    "get_card_status": CardArgs,
    "get_transaction_history": HistoryArgs,
    "score_transaction": ScoreArgs,
    "block_card": BlockCardArgs,
    "search_procedures": SearchArgs,
    "activate_skill": SkillArgs,
}
