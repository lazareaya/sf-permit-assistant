from app import rag


def test_chunks_cover_all_procedures():
    ids = {c.procedure_id for c in rag.load_chunks()}
    assert ids == {f"PROC-{i:02d}" for i in range(1, 13)}


def test_search_returns_top3_with_sources():
    out = rag.search_procedures("API de scoring indisponible, que faire ?")
    assert len(out["passages"]) == 3
    for p in out["passages"]:
        assert p["procedure_id"].startswith("PROC-")
        assert p["source"].endswith(".md") and p["section"]
    assert out["passages"][0]["procedure_id"] == "PROC-07"


def test_search_finds_blocking_procedure():
    ids = [
        p["procedure_id"]
        for p in rag.search_procedures("quand bloquer une carte")["passages"]
    ]
    assert "PROC-01" in ids


def test_procedure_exists():
    assert rag.procedure_exists("PROC-01")
    assert not rag.procedure_exists("PROC-99")


def test_search_input_validated():
    assert rag.search_procedures("")["error"] == "INVALID_INPUT"
