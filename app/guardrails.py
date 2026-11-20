"""Guardrails, implemented as ADK callbacks.

``before_tool`` (input guardrails) runs before every tool call and can veto it;
the returned dict becomes the tool result the model sees:
  1. budget: max N business tool calls per user request;
  2. skill allowlist: a tool runs only if the active skill allows it;
  3. Pydantic validation of the arguments (``app/schemas.py``);
  4. unknown project refused;
  5. ``create_submission_draft`` must cite at least one official source
     retrieved by ``search_city_docs`` (no RAG content without its source);
  6. ``send_submission`` refused unless the submission is ``approved`` by a human.

``after_tool`` updates the case memory used by the context builder.

``after_model`` (output guardrail) runs on every final answer: it appends the
legal disclaimer when missing, and the retrieved sources when official
documents were used in this request but no source URL is cited.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from google.adk.agents.callback_context import CallbackContext
from google.adk.models import LlmResponse
from google.adk.tools import BaseTool, ToolContext
from google.genai import types
from pydantic import ValidationError

from app import config, db
from app.config import DISCLAIMER
from app.schemas import TOOL_ARG_MODELS
from app.skills import SKILL_REGISTRY

logger = logging.getLogger("sf_permit_assistant.guardrails")
UNCOUNTED_TOOLS = {"activate_skill"}
URL_RE = re.compile(r"https?://\S+")


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
            f"Limite de {config.MAX_TOOL_CALLS_PER_REQUEST} appels d'outils atteinte pour cette "
            "demande. Conclus avec les informations disponibles.",
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
    parsed = None
    if model is not None:
        try:
            parsed = model(**args)
        except ValidationError as exc:
            details = "; ".join(
                f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()
            )
            return _refuse("INVALID_INPUT", details, tool_name)

    # 4. unknown project
    project_id = getattr(parsed, "project_id", None)
    if project_id is not None and not db.project_exists(project_id):
        return _refuse(
            "PROJECT_NOT_FOUND",
            f"Le projet {project_id} n'existe pas dans la base du cabinet.",
            tool_name,
        )

    # 5. a draft must cite at least one official source retrieved in this conversation
    if tool_name == "create_submission_draft":
        cited = (state.get("case") or {}).get("cited_sources", [])
        if not cited or not any(url in parsed.content for url in cited):
            return _refuse(
                "GUARDRAIL_NO_SOURCE",
                "Le brouillon doit citer au moins une source officielle (URL) retrouvée par "
                f"search_city_docs. Sources disponibles : {cited or 'aucune'}.",
                tool_name,
            )

    # 6. risky action: only an approved submission can be sent
    if tool_name == "send_submission":
        try:
            status = db.get_submission(parsed.submission_id)["status"]
        except db.SubmissionNotFoundError:
            return _refuse(
                "SUBMISSION_NOT_FOUND",
                f"Le dossier {parsed.submission_id} n'existe pas.",
                tool_name,
            )
        if status != "approved":
            return _refuse(
                "GUARDRAIL_NOT_APPROVED",
                f"Envoi refusé : le dossier {parsed.submission_id} est au statut « {status} ». "
                "Seul un dossier approuvé par un humain dans l'interface peut être envoyé.",
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
    tool_name: str,
    args: dict[str, Any],
    payload: dict[str, Any],
    state: Any,
    invocation_id: str = "",
) -> None:
    case = dict(state.get("case") or {})
    if "error" in payload:
        case["errors"] = [*case.get("errors", []), f"{tool_name}: {payload['error']}"][
            -5:
        ]
    elif tool_name == "search_permits":
        case.update(
            address=payload.get("address"), permit_count=payload.get("permit_count")
        )
    elif tool_name == "get_project":
        case.update(
            project_id=payload.get("id"),
            address=payload.get("address"),
            work_type=payload.get("work_type"),
        )
    elif tool_name == "search_city_docs":
        passages = payload.get("passages", [])
        urls = [p["url"] for p in passages]
        case["cited_sources"] = list(
            dict.fromkeys([*case.get("cited_sources", []), *urls])
        )
        if passages:
            state["rag_sources_this_request"] = {
                "invocation": invocation_id,
                "sources": list({p["url"]: p["title"] for p in passages}.items()),
            }
    elif tool_name == "create_submission_draft":
        case["submission_id"] = payload.get("submission_id")
    state["case"] = case


def after_tool(
    tool: BaseTool, args: dict[str, Any], tool_context: ToolContext, tool_response: Any
) -> None:
    update_case(
        tool.name,
        args,
        unwrap_tool_response(tool_response),
        tool_context.state,
        tool_context.invocation_id,
    )
    return None


def enforce_output(text: str, rag_sources: list[tuple[str, str]] | None) -> str:
    """Pure output guardrail: add missing sources and the disclaimer."""
    out = text.rstrip()
    if rag_sources and not URL_RE.search(out):
        out += "\n\n**Sources :**\n" + "\n".join(
            f"- [{title}]({url})" for url, title in rag_sources
        )
    if "pas un avis juridique" not in out.lower():
        out += f"\n\n⚠️ {DISCLAIMER}"
    return out


def after_model(
    callback_context: CallbackContext, llm_response: LlmResponse
) -> LlmResponse | None:
    content = llm_response.content
    if llm_response.partial or not content or not content.parts:
        return None
    if any(p.function_call for p in content.parts):
        return None  # intermediate step, not the final answer
    texts = [p for p in content.parts if p.text and not p.thought]
    if not texts:
        return None
    rag = callback_context.state.get("rag_sources_this_request") or {}
    sources = (
        rag.get("sources")
        if rag.get("invocation") == callback_context.invocation_id
        else None
    )
    full = "".join(p.text for p in texts)
    fixed = enforce_output(full, sources)
    if fixed == full:
        return None
    other = [p for p in content.parts if not (p.text and not p.thought)]
    llm_response.content = types.Content(
        role=content.role, parts=[*other, types.Part(text=fixed)]
    )
    return llm_response
