"""Code metrics on the trace (no LLM): number of tool errors.

A tool error is a tool result that signals a *misuse* by the model: invalid
arguments, guardrail refusals, unknown skill/procedure. Expected business
errors (unknown card, API down) are not counted: reporting them is correct.
"""

import json

MISUSE = (
    "INVALID_INPUT",
    "GUARDRAIL_",
    "UNKNOWN_SKILL",
    "UNKNOWN_PROCEDURE",
    "ALREADY_BLOCKED",
)


def _responses(agent_data):
    for turn in (
        (agent_data or {}).get("turns", []) if isinstance(agent_data, dict) else []
    ):
        for event in turn.get("events", []):
            for part in (event.get("content") or {}).get("parts", []):
                if "function_response" in part:
                    yield part["function_response"]


def evaluate(instance):
    errors = [
        r.get("name")
        for r in _responses(instance.get("agent_data"))
        if any(
            code in json.dumps(r.get("response", ""), ensure_ascii=False)
            for code in MISUSE
        )
    ]
    return {
        "score": len(errors),
        "explanation": ", ".join(filter(None, errors)) or "none",
    }
