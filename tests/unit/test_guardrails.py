from app import config
from app.guardrails import check_tool_call, unwrap_tool_response, update_case

INV = "inv-1"


def test_tool_refused_without_active_skill(state):
    out = check_tool_call("get_card_status", {"card_id": "CARD-00001"}, state, INV)
    assert out["error"] == "GUARDRAIL_SKILL"


def test_tool_refused_outside_active_skill(state):
    state["active_skill"] = "procedure_lookup"
    out = check_tool_call("score_transaction", {"tx_id": 100001}, state, INV)
    assert out["error"] == "GUARDRAIL_SKILL" and "investigation" in out["message"]


def test_allowed_tool_passes(state):
    state["active_skill"] = "investigation"
    assert (
        check_tool_call("get_card_status", {"card_id": "CARD-00001"}, state, INV)
        is None
    )


def test_pydantic_validation(state):
    state["active_skill"] = "investigation"
    assert (
        check_tool_call("score_transaction", {"tx_id": "abc"}, state, INV)["error"]
        == "INVALID_INPUT"
    )


def test_unknown_card_refused(state):
    state["active_skill"] = "investigation"
    assert (
        check_tool_call("get_card_status", {"card_id": "CARD-99999"}, state, INV)[
            "error"
        ]
        == "CARD_NOT_FOUND"
    )


def test_tool_budget_per_request(state, monkeypatch):
    monkeypatch.setattr(config, "MAX_TOOL_CALLS_PER_REQUEST", 3)
    state["active_skill"] = "investigation"
    args = {"card_id": "CARD-00001"}
    assert all(
        check_tool_call("get_card_status", args, state, INV) is None for _ in range(3)
    )
    assert (
        check_tool_call("get_card_status", args, state, INV)["error"]
        == "GUARDRAIL_TOOL_BUDGET"
    )
    # a new user request (new invocation) gets a fresh budget
    assert check_tool_call("get_card_status", args, state, "inv-2") is None


def test_activate_skill_not_counted(state, monkeypatch):
    monkeypatch.setattr(config, "MAX_TOOL_CALLS_PER_REQUEST", 1)
    for _ in range(5):
        assert (
            check_tool_call(
                "activate_skill", {"skill_name": "investigation"}, state, INV
            )
            is None
        )


BLOCK = {
    "card_id": "CARD-00185",
    "procedure_id": "PROC-01",
    "justification": "score 0.99 + 3 pays étrangers",
}


def test_block_card_refused_without_cited_procedure(state):
    state["active_skill"] = "decision_prep"
    assert (
        check_tool_call("block_card", BLOCK, state, INV)["error"]
        == "GUARDRAIL_NO_PROCEDURE"
    )


def test_block_card_allowed_after_procedure_retrieved(state):
    update_case(
        "search_procedures", {}, {"passages": [{"procedure_id": "PROC-01"}]}, state
    )
    state["active_skill"] = "decision_prep"
    assert check_tool_call("block_card", BLOCK, state, INV) is None


def test_update_case_tracks_score_and_errors(state):
    update_case(
        "score_transaction",
        {},
        {"tx_id": 1, "card_id": "CARD-00001", "fraud_probability": 0.9},
        state,
    )
    update_case("score_transaction", {}, {"error": "FRAUD_API_UNAVAILABLE"}, state)
    assert state["case"]["fraud_probability"] == 0.9
    assert state["case"]["errors"] == ["score_transaction: FRAUD_API_UNAVAILABLE"]


def test_unwrap_mcp_response():
    mcp = {"content": [{"type": "text", "text": '{"a": 1}'}], "isError": False}
    assert unwrap_tool_response(mcp) == {"a": 1}
    assert unwrap_tool_response({"structuredContent": {"result": {"a": 2}}}) == {"a": 2}
    assert unwrap_tool_response({"a": 3}) == {"a": 3}
