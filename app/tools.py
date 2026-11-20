"""Business tools of the SF permit assistant.

Single source of truth: the MCP server (``mcp_server/server.py``) exposes these
functions and the unit tests call them directly. Every tool validates its input
with Pydantic and returns a JSON-able dict; failures come back as
``{"error": CODE, "message": ...}`` so the model can explain them.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from app import datasf, db
from app.schemas import AddressArgs, DraftArgs, ProjectArgs, SubmissionArgs


def _error(code: str, message: str) -> dict[str, Any]:
    return {"error": code, "message": message}


def _validation_error(exc: ValidationError) -> dict[str, Any]:
    details = "; ".join(
        f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()
    )
    return _error("INVALID_INPUT", details)


def search_permits(address: str) -> dict[str, Any]:
    """Building permits recorded by the city at an address (DataSF API)."""
    try:
        args = AddressArgs(address=address)
        return datasf.search_permits(args.address)
    except ValidationError as exc:
        return _validation_error(exc)
    except datasf.DataSFError as exc:
        return _error(exc.code, exc.message)


def list_projects() -> dict[str, Any]:
    """Read-only: all projects of the firm (id, client, address, work type, status)."""
    return {"projects": db.list_projects()}


def get_project(project_id: int) -> dict[str, Any]:
    """Read-only: one project of the firm with its submissions."""
    try:
        args = ProjectArgs(project_id=project_id)
        return db.get_project(args.project_id)
    except ValidationError as exc:
        return _validation_error(exc)
    except db.ProjectNotFoundError:
        return _error(
            "PROJECT_NOT_FOUND",
            f"Le projet {project_id} n'existe pas dans la base du cabinet.",
        )


def create_submission_draft(project_id: int, content: str) -> dict[str, Any]:
    """Save a submission draft. It is NOT sent: status pending_approval."""
    try:
        args = DraftArgs(project_id=project_id, content=content)
        res = db.create_submission_draft(args.project_id, args.content)
    except ValidationError as exc:
        return _validation_error(exc)
    except db.ProjectNotFoundError:
        return _error(
            "PROJECT_NOT_FOUND",
            f"Le projet {project_id} n'existe pas dans la base du cabinet.",
        )
    return {
        **res,
        "project_id": args.project_id,
        "message": "Brouillon enregistré, EN ATTENTE DE VALIDATION HUMAINE. Il n'est pas envoyé.",
    }


def send_submission(submission_id: int) -> dict[str, Any]:
    """RISKY ACTION: send an approved submission (simulated). Refused unless approved."""
    try:
        args = SubmissionArgs(submission_id=submission_id)
        return {
            **db.send_submission(args.submission_id),
            "message": "Dossier envoyé (envoi simulé : aucun dépôt réel auprès de la ville).",
        }
    except ValidationError as exc:
        return _validation_error(exc)
    except db.SubmissionNotFoundError:
        return _error(
            "SUBMISSION_NOT_FOUND", f"Le dossier {submission_id} n'existe pas."
        )
    except db.NotApprovedError as exc:
        return _error(
            "NOT_APPROVED",
            f"Envoi refusé : le dossier {submission_id} est au statut « {exc} ». "
            "Il doit d'abord être approuvé par un humain dans l'interface.",
        )
