"""Central configuration (paths and environment variables)."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

BANK_DB_PATH = Path(os.getenv("BANK_DB_PATH", ROOT / "data" / "bank.db"))
PROCEDURES_DIR = Path(os.getenv("PROCEDURES_DIR", ROOT / "data" / "procedures"))
CHROMA_DIR = Path(os.getenv("CHROMA_DIR", ROOT / "data" / "chroma"))

# Project 2 fraud-detection API (FastAPI + XGBoost served from MLflow).
FRAUD_API_URL = os.getenv("FRAUD_API_URL", "http://localhost:8001").rstrip("/")
FRAUD_API_KEY = os.getenv("FRAUD_API_KEY", "")  # injected from Secret Manager in prod
FRAUD_API_TIMEOUT_S = float(os.getenv("FRAUD_API_TIMEOUT_S", "8"))

MODEL = os.getenv("AGENT_MODEL", "gemini-3.8-flash")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "gemini-embedding-001")

# Guardrails
MAX_TOOL_CALLS_PER_REQUEST = int(os.getenv("MAX_TOOL_CALLS_PER_REQUEST", "10"))


def gemini_configured() -> bool:
    """True when a Gemini backend (AI Studio key or Google Cloud project) is set."""
    if os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"):
        return True
    project = os.getenv("GOOGLE_CLOUD_PROJECT", "")
    return bool(project) and project != "your-gcp-project-id"
