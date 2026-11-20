import shutil

import pytest

from app import config


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    """Every test works on a throw-away copy of the bank database."""
    db_copy = tmp_path / "bank.db"
    shutil.copy(config.ROOT / "data" / "bank.db", db_copy)
    monkeypatch.setattr(config, "BANK_DB_PATH", db_copy)
    monkeypatch.setenv("BANK_DB_PATH", str(db_copy))
    return db_copy


@pytest.fixture(scope="session", autouse=True)
def local_embeddings(tmp_path_factory):
    """Offline, deterministic embeddings for the RAG tests."""
    mp = pytest.MonkeyPatch()
    mp.setenv("RAG_EMBEDDINGS", "local")
    mp.setattr(config, "CHROMA_DIR", tmp_path_factory.mktemp("chroma"))
    from app import rag

    rag.get_index.cache_clear()
    yield
    mp.undo()


class FakeState(dict):
    """Stand-in for ADK session state."""


@pytest.fixture
def state():
    return FakeState()
