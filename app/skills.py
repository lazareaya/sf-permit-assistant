"""Skill registry + context builder.

A *skill* = a name, a short description (always visible to the model), full
instructions (injected only when the skill is active) and the list of tools it
is allowed to use (enforced by ``guardrails.before_tool``).

The **context builder** (``build_instruction``) is an ADK ``InstructionProvider``:
it rebuilds the system prompt before every model call from
  1. the base rules,
  2. the skill catalogue (one line per skill),
  3. the full instructions of the *active* skill only,
  4. the facts of the current case that this skill needs (case memory).
Nothing else is injected, which keeps the prompt short and focused.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.tools import ToolContext


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    instructions: str
    allowed_tools: tuple[str, ...]
    context_keys: tuple[str, ...] = field(default_factory=tuple)


SKILL_REGISTRY: dict[str, Skill] = {
    "investigation": Skill(
        name="investigation",
        description="Rassembler les faits : statut de la carte, historique SQL, score du modèle de fraude.",
        instructions=(
            "1. Si on te donne une transaction (tx_id), appelle score_transaction : la réponse contient "
            "la carte (card_id), le montant, la catégorie, le pays et le score.\n"
            "2. Appelle get_card_status puis get_transaction_history sur la carte.\n"
            "3. Relève les signaux : catégories à risque, pays étrangers, montant vs moyenne, rafales.\n"
            "4. Si un outil renvoie une erreur (CARD_NOT_FOUND, TRANSACTION_NOT_FOUND, "
            "FRAUD_API_UNAVAILABLE), ne l'invente pas, ne la contourne pas : note-la et passe à la "
            "recherche de procédure.\n"
            "N'invente JAMAIS de score ni de transaction."
        ),
        allowed_tools=(
            "get_card_status",
            "get_transaction_history",
            "score_transaction",
        ),
        context_keys=("card_id", "tx_id"),
    ),
    "procedure_lookup": Skill(
        name="procedure_lookup",
        description="Trouver la procédure interne applicable (RAG sur les procédures de la banque).",
        instructions=(
            "Appelle search_procedures avec une question précise qui décrit la situation "
            "(niveau de score, signaux, erreur rencontrée). Tu peux faire 2 recherches maximum.\n"
            "Retiens l'identifiant (PROC-XX) des passages qui s'appliquent : tu devras le citer."
        ),
        allowed_tools=("search_procedures",),
        context_keys=("card_id", "tx_id", "fraud_probability", "errors"),
    ),
    "decision_prep": Skill(
        name="decision_prep",
        description="Proposer une action justifiée (ex. blocage) soumise à validation humaine.",
        instructions=(
            "Décide selon la procédure citée :\n"
            "- Si la procédure demande un blocage (score >= 0,90 ou score élevé + signaux aggravants) : "
            "appelle block_card avec card_id, tx_id, une justification (score, signaux) et le "
            "procedure_id. La carte n'est PAS bloquée tant qu'un humain n'a pas approuvé.\n"
            "- Sinon (score faible, carte inconnue, API indisponible, carte déjà bloquée) : "
            "n'appelle PAS block_card, recommande l'action prévue (classer, contacter le client, "
            "escalader N2...).\n"
            "Termine par la réponse finale au format demandé."
        ),
        allowed_tools=("block_card", "get_card_status"),
        context_keys=(
            "card_id",
            "tx_id",
            "fraud_probability",
            "card_status",
            "errors",
            "cited_procedures",
            "pending_action",
        ),
    ),
}

BASE_RULES = """Tu es un assistant pour analystes fraude d'une banque. Tu instruis les alertes \
de fraude carte. Tu réponds en français, de façon factuelle et concise.

Méthode : tu travailles avec des skills. Active une skill avec activate_skill(skill_name) \
avant d'utiliser ses outils. Enchaînement habituel : investigation -> procedure_lookup -> \
decision_prep.

Règles non négociables :
- Ne jamais inventer un score, une transaction, une carte ou une procédure.
- Toute recommandation cite la procédure appliquée (PROC-XX).
- Tu ne bloques jamais une carte toi-même : block_card crée une demande qui attend la \
validation d'un humain. Dis-le clairement.
- Hors périmètre (questions sans lien avec une alerte de fraude) : refuse poliment sans \
appeler d'outil et rappelle ce que tu sais faire (PROC-12).

Format de la réponse finale :
**Synthèse** (2-3 phrases) / **Faits** (score, signaux) / **Procédure appliquée** (PROC-XX) / \
**Action proposée** (et son statut : en attente de validation humaine, ou aucune action)."""


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
            "Aucune skill active. Commence par activate_skill('investigation') "
            "si la demande concerne une carte ou une transaction."
        )
    return "\n\n".join(parts)


def activate_skill(skill_name: str, tool_context: ToolContext) -> dict[str, Any]:
    """Activate a skill (investigation, procedure_lookup or decision_prep).
    Its instructions and allowed tools become available on the next step.

    Args:
        skill_name: one of investigation, procedure_lookup, decision_prep.
    """
    skill = SKILL_REGISTRY.get(skill_name)
    if skill is None:
        return {"error": "UNKNOWN_SKILL", "available": list(SKILL_REGISTRY)}
    tool_context.state["active_skill"] = skill.name
    return {"active_skill": skill.name, "allowed_tools": list(skill.allowed_tools)}
