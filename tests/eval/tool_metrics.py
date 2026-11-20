"""Code metric: number of tool errors caused by a *misuse* of the tools by the
model (invalid arguments, guardrail refusals, unknown skill). Expected business
errors (unknown address, DataSF down, unknown project, NOT_APPROVED when the
user asks to send) are not counted: reporting them is the correct behaviour."""

import json

MISUSE = (
    "INVALID_INPUT",
    "GUARDRAIL_SKILL",
    "GUARDRAIL_TOOL_BUDGET",
    "GUARDRAIL_NO_SOURCE",
    "UNKNOWN_SKILL",
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
