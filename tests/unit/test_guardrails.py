from app import config
from app.config import DISCLAIMER
from app.guardrails import (
    check_tool_call,
    enforce_output,
    unwrap_tool_response,
    update_case,
)

INV = "inv-1"
DRAFT = {
    "project_id": 1,
    "content": "Pièces requises (source : https://example.test/kitchen-remodel). " * 5,
}


def test_tool_refused_without_active_skill(state):
    assert (
        check_tool_call("search_permits", {"address": "781 20th Ave"}, state, INV)[
            "error"
        ]
        == "GUARDRAIL_SKILL"
    )


def test_tool_refused_outside_active_skill(state):
    state["active_skill"] = "permit_search"
    out = check_tool_call("search_city_docs", {"question": "adu"}, state, INV)
    assert (
        out["error"] == "GUARDRAIL_SKILL" and "document_requirements" in out["message"]
    )


def test_allowed_tool_passes(state):
    state["active_skill"] = "permit_search"
    assert (
        check_tool_call("search_permits", {"address": "781 20th Ave"}, state, INV)
        is None
    )


def test_pydantic_validation(state):
    state["active_skill"] = "submission_prep"
    assert (
        check_tool_call("get_project", {"project_id": "abc"}, state, INV)["error"]
        == "INVALID_INPUT"
    )


def test_unknown_project_refused(state):
    state["active_skill"] = "submission_prep"
    assert (
        check_tool_call("get_project", {"project_id": 999}, state, INV)["error"]
        == "PROJECT_NOT_FOUND"
    )


def test_tool_budget_per_request(state, monkeypatch):
    monkeypatch.setattr(config, "MAX_TOOL_CALLS_PER_REQUEST", 2)
    state["active_skill"] = "permit_search"
    args = {"address": "781 20th Ave"}
    assert check_tool_call("search_permits", args, state, INV) is None
    assert check_tool_call("search_permits", args, state, INV) is None
    assert (
        check_tool_call("search_permits", args, state, INV)["error"]
        == "GUARDRAIL_TOOL_BUDGET"
    )
    assert (
        check_tool_call("search_permits", args, state, "inv-2") is None
    )  # new request


def test_activate_skill_not_counted(state, monkeypatch):
    monkeypatch.setattr(config, "MAX_TOOL_CALLS_PER_REQUEST", 1)
    for _ in range(5):
        assert (
            check_tool_call(
                "activate_skill", {"skill_name": "permit_search"}, state, INV
            )
            is None
        )


def test_draft_refused_without_retrieved_source(state):
    state["active_skill"] = "submission_prep"
    assert (
        check_tool_call("create_submission_draft", DRAFT, state, INV)["error"]
        == "GUARDRAIL_NO_SOURCE"
    )


def test_draft_allowed_when_it_cites_a_retrieved_source(state):
    update_case(
        "search_city_docs",
        {},
        {"passages": [{"url": "https://example.test/kitchen-remodel", "title": "T"}]},
        state,
        INV,
    )
    state["active_skill"] = "submission_prep"
    assert check_tool_call("create_submission_draft", DRAFT, state, INV) is None


def test_send_refused_unless_approved(state):
    state["active_skill"] = "submission_prep"
    assert (
        check_tool_call("send_submission", {"submission_id": 1}, state, INV)["error"]
        == "GUARDRAIL_NOT_APPROVED"
    )
    assert (
        check_tool_call("send_submission", {"submission_id": 3}, state, INV)["error"]
        == "GUARDRAIL_NOT_APPROVED"
    )
    assert (
        check_tool_call("send_submission", {"submission_id": 2}, state, INV) is None
    )  # seed #2 approved
    assert (
        check_tool_call("send_submission", {"submission_id": 999}, state, INV)["error"]
        == "SUBMISSION_NOT_FOUND"
    )


def test_output_guardrail_adds_disclaimer_and_sources():
    out = enforce_output(
        "Il faut des plans.", [("https://example.test/kitchen-remodel", "Kitchen")]
    )
    assert (
        "[Kitchen](https://example.test/kitchen-remodel)" in out and DISCLAIMER in out
    )
    ok = f"Voir https://x.test.\n\n⚠️ {DISCLAIMER}"
    assert (
        enforce_output(ok, [("https://y", "Y")]) == ok
    )  # already compliant: unchanged
    assert DISCLAIMER in enforce_output("Je ne traite pas cette demande.", None)


def test_update_case_tracks_facts(state):
    update_case(
        "search_permits", {}, {"address": "781 20th Av", "permit_count": 8}, state
    )
    update_case(
        "get_project",
        {},
        {"id": 1, "address": "781 20th Ave", "work_type": "kitchen_remodel"},
        state,
    )
    update_case("search_permits", {}, {"error": "DATASF_TIMEOUT"}, state)
    assert (
        state["case"]["permit_count"] == 8
        and state["case"]["work_type"] == "kitchen_remodel"
    )
    assert state["case"]["errors"] == ["search_permits: DATASF_TIMEOUT"]


def test_unwrap_mcp_response():
    assert unwrap_tool_response(
        {"content": [{"type": "text", "text": '{"a": 1}'}]}
    ) == {"a": 1}
    assert unwrap_tool_response({"structuredContent": {"result": {"a": 2}}}) == {"a": 2}
    assert unwrap_tool_response({"a": 3}) == {"a": 3}
