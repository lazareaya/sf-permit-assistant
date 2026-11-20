"""Central configuration (paths and environment variables)."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

DISCLAIMER = (
    "Information générale, pas un avis juridique. "
    "Vérifier auprès du Department of Building Inspection."
)

PROJECTS_DB_PATH = Path(os.getenv("PROJECTS_DB_PATH", ROOT / "data" / "projects.db"))
CITY_DOCS_DIR = Path(os.getenv("CITY_DOCS_DIR", ROOT / "data" / "city_docs"))
CHROMA_DIR = Path(os.getenv("CHROMA_DIR", ROOT / "data" / "chroma"))

# DataSF "Building Permits" (Socrata API, public, no key required)
DATASF_URL = os.getenv("DATASF_URL", "https://data.sf.gov/resource/i98e-djp9.json")
DATASF_TIMEOUT_S = float(os.getenv("DATASF_TIMEOUT_S", "10"))
DATASF_CACHE = os.getenv("DATASF_CACHE", "on").lower() != "off"
DATASF_CACHE_TTL_S = int(os.getenv("DATASF_CACHE_TTL_S", str(24 * 3600)))
DATASF_CACHE_PATH = Path(
    os.getenv("DATASF_CACHE_PATH", ROOT / "data" / "cache" / "datasf.sqlite")
)
# Optional Socrata app token (higher rate limits); from Secret Manager in prod.
SOCRATA_APP_TOKEN = os.getenv("SOCRATA_APP_TOKEN", "")

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
