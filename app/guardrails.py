"""Guardrails, implemented as ADK tool callbacks.

``before_tool`` runs before every tool call and can veto it (returning a dict
short-circuits the tool and the dict becomes the tool result the LLM sees):
  1. budget: max N business tool calls per user request;
  2. skill allowlist: a tool can only run if the active skill allows it;
  3. input validation with Pydantic (``app/schemas.py``);
  4. refusal if the card does not exist;
  5. no ``block_card`` without a procedure retrieved by ``search_procedures``.

``after_tool`` updates the *case memory* (``state["case"]``) used by the
context builder, and never alters the tool result.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from google.adk.tools import BaseTool, ToolContext
from pydantic import ValidationError

from app import config, db
from app.schemas import TOOL_ARG_MODELS
from app.skills import SKILL_REGISTRY

logger = logging.getLogger("fraud_agent.guardrails")
UNCOUNTED_TOOLS = {"activate_skill"}


def _refuse(code: str, message: str, tool_name: str) -> dict[str, Any]:
    logger.warning("guardrail %s on %s: %s", code, tool_name, message)
    return {"error": code, "message": message, "blocked_by_guardrail": True}


def _skill_for(tool_name: str) -> str | None:
    return next(
        (s.name for s in SKILL_REGISTRY.values() if tool_name in s.allowed_tools), None
    )


def check_tool_call(
    tool_name: str, args: dict[str, Any], state: Any, invocation_id: str
) -> dict[str, Any] | None:
    """Pure guardrail logic (unit-testable without ADK). Returns a refusal or None."""
    if tool_name in UNCOUNTED_TOOLS:
        return None

    # 1. tool-call budget per user request (one ADK invocation = one request)
    budget = dict(state.get("tool_budget") or {})
    if budget.get("invocation") != invocation_id:
        budget = {"invocation": invocation_id, "count": 0}
    budget["count"] += 1
    state["tool_budget"] = budget
    if budget["count"] > config.MAX_TOOL_CALLS_PER_REQUEST:
        return _refuse(
            "GUARDRAIL_TOOL_BUDGET",
            f"Limite de {config.MAX_TOOL_CALLS_PER_REQUEST} appels d'outils atteinte pour cette demande. "
            "Conclus avec les informations disponibles.",
            tool_name,
        )

    # 2. skill allowlist
    active = state.get("active_skill")
    skill = SKILL_REGISTRY.get(active) if active else None
    if skill is None or tool_name not in skill.allowed_tools:
        return _refuse(
            "GUARDRAIL_SKILL",
            f"L'outil {tool_name} n'est pas autorisé dans la skill active ({active}). "
            f"Active d'abord la skill '{_skill_for(tool_name)}'.",
            tool_name,
        )

    # 3. input validation
    model = TOOL_ARG_MODELS.get(tool_name)
    if model is not None:
        try:
            parsed = model(**args)
        except ValidationError as exc:
            details = "; ".join(
                f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()
            )
            return _refuse("INVALID_INPUT", details, tool_name)
    else:
        parsed = None

    # 4. unknown card
    card_id = getattr(parsed, "card_id", None)
    if card_id and not db.card_exists(card_id):
        return _refuse(
            "CARD_NOT_FOUND",
            f"La carte {card_id} n'existe pas. Aucune action possible (PROC-06).",
            tool_name,
        )

    # 5. no risky action without a cited procedure
    if tool_name == "block_card":
        cited = (state.get("case") or {}).get("cited_procedures", [])
        if parsed.procedure_id not in cited:
            return _refuse(
                "GUARDRAIL_NO_PROCEDURE",
                f"block_card exige une procédure retrouvée via search_procedures. "
                f"Procédures consultées : {cited or 'aucune'}.",
                tool_name,
            )
    return None


def before_tool(
    tool: BaseTool, args: dict[str, Any], tool_context: ToolContext
) -> dict[str, Any] | None:
    return check_tool_call(
        tool.name, args, tool_context.state, tool_context.invocation_id
    )


def unwrap_tool_response(resp: Any) -> dict[str, Any]:
    """MCP tools return a CallToolResult dump; function tools return the dict itself."""
    if not isinstance(resp, dict):
        return {"result": resp}
    structured = resp.get("structuredContent")
    if isinstance(structured, dict):
        return (
            structured.get("result", structured) if len(structured) == 1 else structured
        )
    content = resp.get("content")
    if (
        isinstance(content, list)
        and content
        and isinstance(content[0], dict)
        and "text" in content[0]
    ):
        try:
            return json.loads(content[0]["text"])
        except (json.JSONDecodeError, TypeError):
            return {"text": content[0]["text"]}
    return resp


def update_case(
    tool_name: str, args: dict[str, Any], payload: dict[str, Any], state: Any
) -> None:
    case = dict(state.get("case") or {})
    if "error" in payload:
        case["errors"] = [*case.get("errors", []), f"{tool_name}: {payload['error']}"]
    elif tool_name == "score_transaction":
        case.update(
            tx_id=payload.get("tx_id"),
            card_id=payload.get("card_id"),
            fraud_probability=payload.get("fraud_probability"),
        )
    elif tool_name == "get_card_status":
        case.update(card_id=payload.get("card_id"), card_status=payload.get("status"))
    elif tool_name == "get_transaction_history":
        case["card_id"] = payload.get("card_id", case.get("card_id"))
    elif tool_name == "search_procedures":
        ids = [p["procedure_id"] for p in payload.get("passages", [])]
        case["cited_procedures"] = sorted(
            set(case.get("cited_procedures", [])) | set(ids)
        )
    elif tool_name == "block_card":
        case["pending_action"] = {
            "action_id": payload.get("action_id"),
            "status": payload.get("status"),
        }
    state["case"] = case


def after_tool(
    tool: BaseTool, args: dict[str, Any], tool_context: ToolContext, tool_response: Any
) -> None:
    update_case(
        tool.name, args, unwrap_tool_response(tool_response), tool_context.state
    )
    return None
