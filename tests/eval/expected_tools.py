"""Code metric: share of the expected business tools actually called (0-1).
For refusal cases ([EXPECT_TOOLS: none]) the score is 1 if no business tool is called."""

import json
import re

BUSINESS = {
    "search_permits",
    "list_projects",
    "get_project",
    "create_submission_draft",
    "send_submission",
    "search_city_docs",
}


def evaluate(instance):
    reference = json.dumps(instance.get("reference", ""), ensure_ascii=False)
    m = re.search(r"\[EXPECT_TOOLS: ([^\]]*)\]", reference)
    expected = {t.strip() for t in (m.group(1) if m else "none").split(",")} - {
        "none",
        "",
    }
    called = set()
    data = instance.get("agent_data") or {}
    for turn in data.get("turns", []) if isinstance(data, dict) else []:
        for event in turn.get("events", []):
            for part in (event.get("content") or {}).get("parts", []):
                if "function_call" in part:
                    called.add(part["function_call"].get("name"))
    called &= BUSINESS
    if not expected:
        return {
            "score": float(not called),
            "explanation": f"no tool expected; called {sorted(called)}",
        }
    return {
        "score": len(expected & called) / len(expected),
        "explanation": f"expected {sorted(expected)}, called {sorted(called)}",
    }
