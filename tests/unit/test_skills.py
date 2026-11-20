from types import SimpleNamespace

from app.skills import SKILL_REGISTRY, activate_skill, build_instruction


def test_registry_has_three_skills_with_disjoint_purposes():
    assert set(SKILL_REGISTRY) == {"investigation", "procedure_lookup", "decision_prep"}
    assert "block_card" in SKILL_REGISTRY["decision_prep"].allowed_tools
    assert "block_card" not in SKILL_REGISTRY["investigation"].allowed_tools


def test_context_builder_injects_only_active_skill():
    ctx = SimpleNamespace(
        state={
            "active_skill": "procedure_lookup",
            "case": {
                "card_id": "CARD-00001",
                "fraud_probability": 0.95,
                "pending_action": {"action_id": 1},
            },
        }
    )
    prompt = build_instruction(ctx)
    assert "Skill active : procedure_lookup" in prompt
    assert SKILL_REGISTRY["procedure_lookup"].instructions in prompt
    assert SKILL_REGISTRY["decision_prep"].instructions not in prompt
    assert "fraud_probability : 0.95" in prompt
    assert "pending_action" not in prompt  # not needed by this skill


def test_context_builder_without_skill():
    prompt = build_instruction(SimpleNamespace(state={}))
    assert "Aucune skill active" in prompt
    for s in SKILL_REGISTRY.values():
        assert s.description in prompt and s.instructions not in prompt


def test_activate_skill_sets_state():
    tc = SimpleNamespace(state={})
    assert activate_skill("decision_prep", tc)["allowed_tools"] == [
        "block_card",
        "get_card_status",
    ]
    assert tc.state["active_skill"] == "decision_prep"
    assert activate_skill("hack", tc)["error"] == "UNKNOWN_SKILL"
