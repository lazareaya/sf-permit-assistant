"""The code metrics of tests/eval/ (no LLM involved)."""

import importlib.util
from pathlib import Path

EVAL = Path(__file__).resolve().parents[1] / "eval"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, EVAL / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.evaluate


def _trace(*parts):
    return {"turns": [{"events": [{"content": {"parts": list(parts)}}]}]}


def _ref(text):
    return {"response": {"parts": [{"text": text}]}}


def test_expected_tools():
    ev = _load("expected_tools")
    inst = {
        "reference": _ref("[EXPECT_TOOLS: get_project,search_city_docs] ..."),
        "agent_data": _trace({"function_call": {"name": "get_project"}}),
    }
    assert ev(inst)["score"] == 0.5
    refusal = {"reference": _ref("[EXPECT_TOOLS: none] ..."), "agent_data": _trace()}
    assert ev(refusal)["score"] == 1.0


def test_source_and_disclaimer():
    ev = _load("source_and_disclaimer")
    ref = _ref(
        "[EXPECT_TOOLS: search_city_docs] [EXPECT_SOURCE: https://www.sf.gov/a|https://www.sf.gov/b] x"
    )
    good = "Voir [A](https://www.sf.gov/b).\n⚠️ Information générale, pas un avis juridique."
    assert ev({"reference": ref, "response": good})["score"] == 1.0
    assert ev({"reference": ref, "response": "Pas de source."})["score"] == 0.0


def test_tool_errors_counts_only_misuse():
    ev = _load("tool_metrics")
    inst = {
        "agent_data": _trace(
            {
                "function_response": {
                    "name": "create_submission_draft",
                    "response": {"error": "GUARDRAIL_NO_SOURCE"},
                }
            },
            {
                "function_response": {
                    "name": "search_permits",
                    "response": {"error": "ADDRESS_NOT_FOUND"},
                }
            },
        )
    }
    assert ev(inst)["score"] == 1
