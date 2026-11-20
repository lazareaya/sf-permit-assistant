"""Skill registry + context builder.

A *skill* = a name, a one-line description (always visible to the model),
full instructions (injected only when the skill is active), the tools it may
use (enforced by ``guardrails.before_tool``) and the case facts it needs.

The **context builder** (``build_instruction``) is an ADK ``InstructionProvider``
that rebuilds the system prompt before every model call from:
  1. the base rules (scope, refusal, disclaimer, citations),
  2. the skill catalogue (one line per skill),
  3. the full instructions of the *active* skill only,
  4. the case facts that this skill needs (``context_keys``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.tools import ToolContext

from app.config import DISCLAIMER


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    instructions: str
    allowed_tools: tuple[str, ...]
    context_keys: tuple[str, ...] = field(default_factory=tuple)


SKILL_REGISTRY: dict[str, Skill] = {
    "permit_search": Skill(
        name="permit_search",
        description="Permis existants à une adresse de San Francisco et leur statut (API DataSF).",
        instructions=(
            "1. Appelle search_permits avec l'adresse (numéro + rue, ex. « 781 20th Ave »).\n"
            "2. Résume : nombre de permis, puis les plus récents (numéro, type, statut, date du statut, "
            "description courte, coût estimé). N'utilise QUE les champs renvoyés par l'outil.\n"
            "3. Cite la source « DataSF — Building Permits » et la date data_as_of.\n"
            "4. Erreurs : ADDRESS_NOT_FOUND -> dis qu'aucun permis n'est trouvé et que l'adresse est "
            "peut-être inexistante ; DATASF_TIMEOUT / DATASF_UNAVAILABLE -> dis que l'API de la ville "
            "est indisponible et propose de réessayer. N'invente jamais de permis."
        ),
        allowed_tools=("search_permits",),
        context_keys=("address", "permit_count"),
    ),
    "document_requirements": Skill(
        name="document_requirements",
        description="Documents et démarches pour un type de travaux (fiches officielles de la ville, RAG).",
        instructions=(
            "1. Appelle search_city_docs avec une question précise, de préférence en anglais "
            "(ex. « documents required for kitchen remodel permit »). 2 recherches au maximum.\n"
            "2. Réponds UNIQUEMENT à partir des passages renvoyés et cite chaque source sous la forme "
            "[titre](url).\n"
            "3. Si l'outil renvoie NO_RELEVANT_DOCUMENT ou CORPUS_EMPTY, ou si les passages ne "
            "répondent pas à la question : dis clairement que l'information n'est pas dans les "
            "documents officiels indexés et oriente vers le DBI. Ne réponds jamais de mémoire."
        ),
        allowed_tools=("search_city_docs",),
        context_keys=("work_type", "cited_sources"),
    ),
    "submission_prep": Skill(
        name="submission_prep",
        description="Préparer le brouillon de dossier d'un projet du cabinet (base SQL + documents officiels).",
        instructions=(
            "1. list_projects si l'identifiant du projet n'est pas connu, sinon get_project.\n"
            "2. search_city_docs pour les documents requis selon le work_type du projet. "
            "search_permits sur l'adresse est optionnel (permis existants).\n"
            "3. Rédige le brouillon en markdown : projet (client, adresse, travaux, coût estimé), "
            "procédure probable, liste des pièces à fournir avec pour chacune sa source [titre](url), "
            "permis existants éventuels, l'avertissement juridique. Puis appelle "
            "create_submission_draft(project_id, content).\n"
            "4. Le brouillon est EN ATTENTE DE VALIDATION HUMAINE : dis-le. Ne l'envoie pas.\n"
            "5. send_submission seulement si l'utilisateur demande explicitement l'envoi d'un dossier "
            "précis. S'il est refusé (NOT_APPROVED), explique qu'un humain doit d'abord l'approuver "
            "dans l'interface. Ne prétends jamais qu'un dossier est envoyé sans succès de l'outil."
        ),
        allowed_tools=(
            "list_projects",
            "get_project",
            "search_city_docs",
            "search_permits",
            "create_submission_draft",
            "send_submission",
        ),
        context_keys=(
            "project_id",
            "address",
            "work_type",
            "cited_sources",
            "submission_id",
        ),
    ),
}

BASE_RULES = f"""Tu es l'assistant permis de construire d'un cabinet d'architectes (fictif) à \
San Francisco. Tu réponds en français, de façon factuelle et concise.

Tu ne traites que 3 types de demandes :
a) les permis existants à une adresse de San Francisco et leur statut -> skill permit_search ;
b) les documents et démarches pour un type de travaux (rénovation de cuisine, salle de bain, \
logement accessoire / ADU, réfection de toiture, panneaux solaires, fenêtres) -> skill \
document_requirements ;
c) la préparation du dossier d'un projet du cabinet -> skill submission_prep.
Active une skill avec activate_skill(skill_name) avant d'utiliser ses outils.

Toute autre demande (autre ville, conseil juridique, fiscalité, sujets sans rapport...) : refuse \
poliment SANS appeler d'outil et explique les 3 choses que tu sais faire.

Règles non négociables :
- N'invente jamais un permis, une exigence, un document ou une URL.
- Toute information issue des documents officiels cite sa source [titre](url).
- Un dossier n'est envoyé qu'après validation humaine ; tu ne contournes jamais ce contrôle.
- Termine CHAQUE réponse par la ligne : « ⚠️ {DISCLAIMER} »"""


def _catalogue() -> str:
    return "\n".join(f"- {s.name} : {s.description}" for s in SKILL_REGISTRY.values())


def build_instruction(ctx: ReadonlyContext) -> str:
    """Context builder: only what the active skill needs."""
    state = ctx.state
    active = state.get("active_skill")
    parts = [BASE_RULES, "Skills disponibles :\n" + _catalogue()]
    if active in SKILL_REGISTRY:
        skill = SKILL_REGISTRY[active]
        parts.append(
            f"Skill active : {skill.name}\nInstructions :\n{skill.instructions}\n"
            f"Outils autorisés : {', '.join(skill.allowed_tools)}"
        )
        case: dict[str, Any] = state.get("case") or {}
        facts = {k: case[k] for k in skill.context_keys if k in case}
        if facts:
            parts.append(
                "Dossier en cours :\n"
                + "\n".join(f"- {k} : {v}" for k, v in facts.items())
            )
    else:
        parts.append(
            "Aucune skill active. Si la demande entre dans le périmètre, active la skill "
            "correspondante ; sinon refuse poliment."
        )
    return "\n\n".join(parts)


def activate_skill(skill_name: str, tool_context: ToolContext) -> dict[str, Any]:
    """Activate a skill (permit_search, document_requirements or submission_prep).
    Its instructions and allowed tools become available on the next step.

    Args:
        skill_name: one of permit_search, document_requirements, submission_prep.
    """
    skill = SKILL_REGISTRY.get(skill_name)
    if skill is None:
        return {"error": "UNKNOWN_SKILL", "available": list(SKILL_REGISTRY)}
    tool_context.state["active_skill"] = skill.name
    return {"active_skill": skill.name, "allowed_tools": list(skill.allowed_tools)}
