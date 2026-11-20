"""MCP server exposing the bank's fraud tools (FastMCP, stdio or HTTP).

Built with the official Python MCP SDK. Its high-level server was called
``FastMCP`` up to SDK v1 and is named ``MCPServer`` since SDK v2 (same API).

The ADK agent does not import these tools: it *discovers* them at runtime
through the Model Context Protocol (``McpToolset`` in ``app/agent.py``).
Any other MCP client (Claude Desktop, Gemini CLI, Cursor...) can use them too.

Tools:
* ``score_transaction``       -> HTTP call to the Project 2 fraud-detection API
* ``get_transaction_history`` -> read-only SQL query
* ``get_card_status``         -> read-only SQL query
* ``block_card``              -> RISKY: only creates a *pending* request in the
                                 ``actions`` table; a human must approve it.

Run:
    uv run python -m mcp_server.server                 # stdio (used by the agent)
    uv run python -m mcp_server.server --http 8765     # streamable HTTP
"""

from __future__ import annotations

import sys
from typing import Any

try:  # MCP SDK v2
    from mcp.server.mcpserver import MCPServer as FastMCP
except ImportError:  # MCP SDK v1
    from mcp.server.fastmcp import FastMCP

from app import tools

mcp = FastMCP(
    "bank-fraud-tools",
    instructions="Outils d'investigation fraude carte : historique SQL, scoring ML, demande de blocage.",
)


@mcp.tool()
def score_transaction(tx_id: int) -> dict[str, Any]:
    """Score une transaction avec le modèle de détection de fraude (API du projet 2, XGBoost).

    Args:
        tx_id: identifiant de la transaction (nombre à 6 chiffres, ex: 100123).

    Returns: fraud_probability (0-1), is_fraud, threshold_used, model_version,
    ou {"error": "FRAUD_API_UNAVAILABLE"} si l'API est en panne.
    """
    return tools.score_transaction(tx_id)


@mcp.tool()
def get_transaction_history(card_id: str, limit: int = 20) -> dict[str, Any]:
    """Historique des dernières transactions d'une carte (requête SQL en lecture seule)
    et statistiques : nombre, montant moyen, montant max, nombre de transactions à l'étranger.

    Args:
        card_id: identifiant de carte au format CARD-00000.
        limit: nombre de transactions à renvoyer (1-100, défaut 20).
    """
    return tools.get_transaction_history(card_id, limit)


@mcp.tool()
def get_card_status(card_id: str) -> dict[str, Any]:
    """Statut d'une carte (active / blocked), titulaire, plafond et dernières actions.

    Args:
        card_id: identifiant de carte au format CARD-00000.
    """
    return tools.get_card_status(card_id)


@mcp.tool()
def block_card(
    card_id: str, justification: str, procedure_id: str, tx_id: int | None = None
) -> dict[str, Any]:
    """ACTION RISQUÉE. Demande le blocage d'une carte. La carte N'EST PAS bloquée :
    une demande « en attente de validation » est créée et un humain doit l'approuver.

    Args:
        card_id: carte à bloquer (CARD-00000).
        justification: score, signaux observés et raisonnement (20 caractères minimum).
        procedure_id: procédure interne appliquée, obligatoire (ex: PROC-01).
        tx_id: transaction à l'origine de la demande.
    """
    return tools.block_card(card_id, justification, procedure_id, tx_id)


if __name__ == "__main__":
    if "--http" in sys.argv:
        port = int(sys.argv[sys.argv.index("--http") + 1])
        mcp.run(transport="streamable-http", host="0.0.0.0", port=port)
    else:
        mcp.run()
