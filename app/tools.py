"""Business tools of the fraud analyst agent.

These plain functions are the single source of truth: the MCP server
(``mcp_server/server.py``) exposes them over MCP, and the unit tests call them
directly. Every tool validates its input with Pydantic and returns a JSON-able
dict; failures are returned as ``{"error": CODE, "message": ...}`` instead of
raising, so the LLM can explain them to the analyst.
"""

from __future__ import annotations

from typing import Any

import httpx
from pydantic import ValidationError

from app import config, db
from app.schemas import BlockCardArgs, CardArgs, HistoryArgs, ScoreArgs


def _error(code: str, message: str) -> dict[str, Any]:
    return {"error": code, "message": message}


def _validation_error(exc: ValidationError) -> dict[str, Any]:
    details = "; ".join(
        f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()
    )
    return _error("INVALID_INPUT", details)


def get_card_status(card_id: str) -> dict[str, Any]:
    """Return the status of a card (active/blocked), its owner and recent actions."""
    try:
        args = CardArgs(card_id=card_id)
        return db.get_card_status(args.card_id)
    except ValidationError as exc:
        return _validation_error(exc)
    except db.CardNotFoundError:
        return _error(
            "CARD_NOT_FOUND", f"La carte {card_id} n'existe pas dans la base."
        )


def get_transaction_history(card_id: str, limit: int = 20) -> dict[str, Any]:
    """Read-only SQL query: latest transactions of a card and summary statistics."""
    try:
        args = HistoryArgs(card_id=card_id, limit=limit)
        return db.get_transaction_history(args.card_id, args.limit)
    except ValidationError as exc:
        return _validation_error(exc)
    except db.CardNotFoundError:
        return _error(
            "CARD_NOT_FOUND", f"La carte {card_id} n'existe pas dans la base."
        )


def score_transaction(tx_id: int) -> dict[str, Any]:
    """Score a transaction with the Project 2 fraud-detection API (XGBoost)."""
    try:
        args = ScoreArgs(tx_id=tx_id)
        tx = db.get_transaction(args.tx_id)
    except ValidationError as exc:
        return _validation_error(exc)
    except db.TransactionNotFoundError:
        return _error("TRANSACTION_NOT_FOUND", f"La transaction {tx_id} n'existe pas.")

    headers = {"X-API-Key": config.FRAUD_API_KEY} if config.FRAUD_API_KEY else {}
    try:
        resp = httpx.post(
            f"{config.FRAUD_API_URL}/predict",
            json=db.fraud_api_payload(tx),
            headers=headers,
            timeout=config.FRAUD_API_TIMEOUT_S,
        )
        resp.raise_for_status()
        result = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        return _error(
            "FRAUD_API_UNAVAILABLE",
            f"L'API de scoring est indisponible ({type(exc).__name__}). "
            "Ne pas conclure sans score : appliquer la procédure de mode dégradé.",
        )
    return {
        "tx_id": tx["tx_id"],
        "card_id": tx["card_id"],
        "amount": tx["amount"],
        "ts": tx["ts"],
        "merchant_category": tx["merchant_category"],
        "country": tx["country"],
        "fraud_probability": round(float(result["fraud_probability"]), 4),
        "is_fraud": bool(result["is_fraud"]),
        "threshold_used": round(float(result["threshold_used"]), 4),
        "model_version": result.get("model_version", "unknown"),
    }


def block_card(
    card_id: str, justification: str, procedure_id: str, tx_id: int | None = None
) -> dict[str, Any]:
    """RISKY ACTION. Request a card block. It is NOT executed: a pending request
    is written to the ``actions`` table and must be approved by a human."""
    from app.rag import procedure_exists

    try:
        args = BlockCardArgs(
            card_id=card_id,
            justification=justification,
            procedure_id=procedure_id,
            tx_id=tx_id,
        )
    except ValidationError as exc:
        return _validation_error(exc)
    if not procedure_exists(args.procedure_id):
        return _error("UNKNOWN_PROCEDURE", f"La procédure {procedure_id} n'existe pas.")
    try:
        status = db.get_card_status(args.card_id)
    except db.CardNotFoundError:
        return _error(
            "CARD_NOT_FOUND", f"La carte {card_id} n'existe pas dans la base."
        )
    if status["status"] == "blocked":
        return _error("ALREADY_BLOCKED", f"La carte {card_id} est déjà bloquée.")
    req = db.create_pending_action(
        args.card_id, args.justification, args.procedure_id, tx_id=args.tx_id
    )
    return {
        **req,
        "card_id": args.card_id,
        "message": (
            "Demande de blocage enregistrée, EN ATTENTE DE VALIDATION HUMAINE. "
            "La carte n'est pas encore bloquée."
        ),
    }
