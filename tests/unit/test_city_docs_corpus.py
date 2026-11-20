"""Ingestion of the REAL corpus (data/city_docs/): 10 official sf.gov pages."""

import sys
from collections import Counter

import pytest

from app import config, rag

sys.path.insert(0, str(config.ROOT / "scripts"))
from fetch_city_docs import PAGES, UNAVAILABLE

DOCS = config.ROOT / "data" / "city_docs"


@pytest.fixture(scope="module")
def chunks():
    return rag.load_chunks(DOCS)


def test_ten_pages_indexed_with_their_source(chunks):
    expected = {doc_id: url for doc_id, _, url in PAGES}
    assert len(expected) == 10
    assert {c.doc_id for c in chunks} == set(expected)
    for c in chunks:
        assert c.url == expected[c.doc_id] and c.title and c.section


def test_missing_pages_are_not_in_the_corpus(chunks):
    assert {d for d, _, _ in UNAVAILABLE} == {"DOC-03", "DOC-07"}
    assert not {c.doc_id for c in chunks} & {"DOC-03", "DOC-07"}


def test_page_type_is_metadata_not_text(chunks):
    types = {c.doc_id: c.page_type for c in chunks}
    assert types["DOC-02"] == "Step-by-step" and types["DOC-04"] == "Info Page"
    assert types["DOC-01"] == ""  # this page has no label
    for c in chunks:
        if c.page_type:
            assert not c.text.split("\n", 1)[1].startswith(c.page_type)


def test_related_and_link_lists_are_dropped(chunks):
    assert not [
        c
        for c in chunks
        if c.section.split(" > ")[0] in {"Related", "Topics", "Departments"}
    ]


def test_contact_us_is_one_chunk_per_document(chunks):
    contact = Counter(c.doc_id for c in chunks if c.section == "Contact us")
    assert contact == {"DOC-01": 1, "DOC-09": 1}
    reroof = next(
        c for c in chunks if c.doc_id == "DOC-09" and c.section == "Contact us"
    )
    assert "628-652-4900" in reroof.text and "PermitSF@sfgov.org" in reroof.text


def test_long_adu_page_is_split_by_heading(chunks):
    adu = [c for c in chunks if c.doc_id == "DOC-05"]
    assert len(adu) >= 20
    assert any(
        c.section == "Decide if your project needs a full or site permit" for c in adu
    )
    assert max(len(c.text) for c in chunks) < 2000


def test_h3_sections_are_labelled_with_their_parent(chunks):
    sections = {c.section for c in chunks if c.doc_id == "DOC-09"}
    assert "What to do > 1. Check if you can get a reroofing permit online" in sections
