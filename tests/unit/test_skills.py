from types import SimpleNamespace

from app.config import DISCLAIMER
from app.skills import SKILL_REGISTRY, activate_skill, build_instruction


def test_registry_has_three_skills():
    assert set(SKILL_REGISTRY) == {
        "permit_search",
        "document_requirements",
        "submission_prep",
    }
    assert SKILL_REGISTRY["permit_search"].allowed_tools == ("search_permits",)
    assert (
        "send_submission" not in SKILL_REGISTRY["document_requirements"].allowed_tools
    )


def test_context_builder_injects_only_active_skill():
    ctx = SimpleNamespace(
        state={
            "active_skill": "document_requirements",
            "case": {"work_type": "adu", "submission_id": 4, "address": "x"},
        }
    )
    prompt = build_instruction(ctx)
    assert "Skill active : document_requirements" in prompt
    assert SKILL_REGISTRY["document_requirements"].instructions in prompt
    assert SKILL_REGISTRY["submission_prep"].instructions not in prompt
    assert "work_type : adu" in prompt and "submission_id" not in prompt
    assert DISCLAIMER in prompt


def test_context_builder_without_skill():
    prompt = build_instruction(SimpleNamespace(state={}))
    assert "Aucune skill active" in prompt
    for s in SKILL_REGISTRY.values():
        assert s.description in prompt and s.instructions not in prompt


def test_activate_skill_sets_state():
    tc = SimpleNamespace(state={})
    assert (
        "create_submission_draft"
        in activate_skill("submission_prep", tc)["allowed_tools"]
    )
    assert tc.state["active_skill"] == "submission_prep"
    assert activate_skill("hack", tc)["error"] == "UNKNOWN_SKILL"
