import shutil
from pathlib import Path

import pytest

from app import config

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    """Every test works on a throw-away copy of the projects database and cache."""
    db_copy = tmp_path / "projects.db"
    shutil.copy(config.ROOT / "data" / "projects.db", db_copy)
    monkeypatch.setattr(config, "PROJECTS_DB_PATH", db_copy)
    monkeypatch.setenv("PROJECTS_DB_PATH", str(db_copy))
    monkeypatch.setattr(config, "DATASF_CACHE_PATH", tmp_path / "datasf.sqlite")
    monkeypatch.setenv("DATASF_CACHE_PATH", str(tmp_path / "datasf.sqlite"))
    return db_copy


@pytest.fixture(scope="session", autouse=True)
def local_rag(tmp_path_factory):
    """Offline embeddings over the synthetic test corpus."""
    mp = pytest.MonkeyPatch()
    mp.setenv("RAG_EMBEDDINGS", "local")
    mp.setattr(config, "CHROMA_DIR", tmp_path_factory.mktemp("chroma"))
    mp.setattr(config, "CITY_DOCS_DIR", FIXTURES / "city_docs")
    from app import rag

    rag.get_index.cache_clear()
    yield
    mp.undo()


@pytest.fixture
def state():
    return {}
