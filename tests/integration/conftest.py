"""Integration tests call Gemini for real: skipped when no backend is configured."""

import pytest

from app import config


@pytest.fixture(autouse=True)
def _require_gemini():
    if not config.gemini_configured():
        pytest.skip(
            "Gemini not configured (set GEMINI_API_KEY or GOOGLE_CLOUD_PROJECT in .env)"
        )
