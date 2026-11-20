"""Pydantic models validating every tool input (guardrail: input validation)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class AddressArgs(BaseModel):
    address: str = Field(
        ...,
        min_length=5,
        max_length=120,
        pattern=r"^[0-9A-Za-z .,'#\-]+$",
        description="ex: 781 20th Ave",
    )


class ProjectArgs(BaseModel):
    project_id: int = Field(..., ge=1, le=100000)


class NoArgs(BaseModel):
    pass


class DraftArgs(ProjectArgs):
    content: str = Field(..., min_length=200, max_length=20000)


class SubmissionArgs(BaseModel):
    submission_id: int = Field(..., ge=1, le=100000)


class QuestionArgs(BaseModel):
    question: str = Field(..., min_length=3, max_length=500)


class SkillArgs(BaseModel):
    skill_name: str = Field(..., min_length=3, max_length=40)


TOOL_ARG_MODELS: dict[str, type[BaseModel]] = {
    "search_permits": AddressArgs,
    "list_projects": NoArgs,
    "get_project": ProjectArgs,
    "create_submission_draft": DraftArgs,
    "send_submission": SubmissionArgs,
    "search_city_docs": QuestionArgs,
    "activate_skill": SkillArgs,
}
