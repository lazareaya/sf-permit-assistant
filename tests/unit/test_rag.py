from app import rag


def test_pages_without_source_are_never_indexed():
    chunks = rag.load_chunks()
    assert {c.doc_id for c in chunks} == {"TEST-01", "TEST-02"}
    assert all(c.url.startswith("https://") and c.title for c in chunks)


def test_search_returns_passages_with_source():
    out = rag.search_city_docs("kitchen remodel plans walls floor plan")
    assert out["passages"]
    top = out["passages"][0]
    assert top["url"] == "https://example.test/kitchen-remodel" and top["title"]


def test_irrelevant_question_returns_no_document():
    out = rag.search_city_docs("zzqx wombat")
    assert out["passages"] == [] and out["status"] == "NO_RELEVANT_DOCUMENT"


def test_front_matter_parser():
    meta, body = rag.parse_front_matter("---\nurl: https://x\ntitle: T\n---\nhello")
    assert meta == {"url": "https://x", "title": "T"} and body == "hello"


def test_input_validated():
    assert rag.search_city_docs("")["error"] == "INVALID_INPUT"
