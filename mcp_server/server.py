"""MCP server exposing the SF permit assistant's tools (FastMCP, stdio or HTTP).

Built with the official Python MCP SDK. Its high-level server was called
``FastMCP`` up to SDK v1 and is named ``MCPServer`` since SDK v2 (same API).

The ADK agent does not import these tools: it *discovers* them at runtime
through the Model Context Protocol (``McpToolset`` in ``app/agent.py``). Any
other MCP client (Claude Desktop, Gemini CLI, Cursor...) can use them too.

Tools:
* ``search_permits``          -> public DataSF Building Permits API (cached)
* ``list_projects``           -> read-only SQL
* ``get_project``             -> read-only SQL
* ``create_submission_draft`` -> writes a draft with status pending_approval
* ``send_submission``         -> RISKY: refused unless status is approved

The RAG tool ``search_city_docs`` stays a direct ADK tool: the Chroma index and
the embedding client live in the agent process, so no extra hop is needed.

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
    "sf-permit-tools",
    instructions="Permis de construire à San Francisco (DataSF) et projets du cabinet d'architectes.",
)


@mcp.tool()
def search_permits(address: str) -> dict[str, Any]:
    """Permis de construire enregistrés par la ville de San Francisco à une adresse
    (API publique DataSF « Building Permits »), du plus récent au plus ancien.

    Args:
        address: numéro + rue à San Francisco, ex. « 781 20th Ave » ou « 2542 Bryant St ».

    Returns: permit_count, permits (permit_number, permit_type_definition, status,
    status_date, filed_date, issued_date, description, estimated_cost...), source,
    data_as_of ; ou une erreur ADDRESS_NOT_FOUND, DATASF_TIMEOUT, DATASF_UNAVAILABLE.
    """
    return tools.search_permits(address)


@mcp.tool()
def list_projects() -> dict[str, Any]:
    """Liste des projets du cabinet (id, client, adresse, type de travaux, statut). Lecture seule."""
    return tools.list_projects()


@mcp.tool()
def get_project(project_id: int) -> dict[str, Any]:
    """Détail d'un projet du cabinet et de ses dossiers déjà créés. Lecture seule.

    Args:
        project_id: identifiant numérique du projet (ex. 3).
    """
    return tools.get_project(project_id)


@mcp.tool()
def create_submission_draft(project_id: int, content: str) -> dict[str, Any]:
    """Enregistre le brouillon de dossier d'un projet, au statut « pending_approval ».
    Le dossier N'EST PAS envoyé : un humain doit l'approuver dans l'interface.

    Args:
        project_id: identifiant du projet.
        content: brouillon complet en markdown, avec les sources officielles citées (URL).
    """
    return tools.create_submission_draft(project_id, content)


@mcp.tool()
def send_submission(submission_id: int) -> dict[str, Any]:
    """ACTION RISQUÉE. Envoie un dossier (envoi simulé). Refusé si le dossier n'a pas été
    approuvé par un humain (statut « approved »).

    Args:
        submission_id: identifiant du dossier.
    """
    return tools.send_submission(submission_id)


if __name__ == "__main__":
    if "--http" in sys.argv:
        port = int(sys.argv[sys.argv.index("--http") + 1])
        mcp.run(transport="streamable-http", host="0.0.0.0", port=port)
    else:
        mcp.run()
