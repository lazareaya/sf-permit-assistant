"""RAG over official City of San Francisco pages (sf.gov: DBI, Planning).

Pipeline: data/city_docs/*.md (one official page each, with a front-matter
header: doc_id, title, url) -> page-type label moved to metadata -> chunks by
``##`` then ``###`` heading (max ~1,500 characters; "Related"/"Topics" link
lists dropped, "Contact us" kept as one chunk) ->
Gemini embeddings (``gemini-embedding-001``) -> Chroma (local persistent vector
store) -> top-3 passages above a relevance threshold, **each with its page
title, section and URL** so the answer can cite "title, section (URL)".

If nothing relevant is found, the tool says so (``NO_RELEVANT_DOCUMENT``)
instead of returning weak passages. If no Gemini backend is configured (CI,
offline unit tests), a deterministic local hashing embedder is used so the
pipeline stays testable; the provider is part of the collection name.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from app import config

TOP_K = 3
MAX_CHUNK_CHARS = 1500
# Cosine-similarity floor below which a passage is considered irrelevant.
MIN_SCORE = {"gemini": float(os.getenv("RAG_MIN_SCORE", "0.55")), "local": 0.12}


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    doc_id: str
    title: str
    url: str
    section: str
    page_type: str
    text: str


# Sections that only list links to other pages: never indexed.
SKIPPED_SECTIONS = {"related", "topics", "departments", "partner agencies"}
# Sections whose sub-sections (###) are kept together in a single chunk.
SINGLE_CHUNK_SECTIONS = {"contact us"}


# ----------------------------------------------------------------- loading
def parse_front_matter(raw: str) -> tuple[dict[str, str], str]:
    if not raw.startswith("---\n"):
        return {}, raw
    head, _, body = raw[4:].partition("\n---\n")
    meta = {}
    for line in head.splitlines():
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip()
    return meta, body


def split_page_header(body: str) -> tuple[str, str]:
    """Return (page_type, body without the label and the H1 title).

    sf.gov pages show a page-type label ("Step-by-step", "Info Page"...) just
    before the H1. It is kept as metadata and removed from the indexed text.
    """
    lines = body.strip().splitlines()
    h1 = next((i for i, line in enumerate(lines) if line.startswith("# ")), None)
    if h1 is None:
        return "", body
    label = " ".join(line.strip() for line in lines[:h1] if line.strip())
    return label, "\n".join(lines[h1 + 1 :])


def _split_long(text: str) -> list[str]:
    """Split on paragraphs, then on sentences for a single very long paragraph."""
    if len(text) <= MAX_CHUNK_CHARS:
        return [text]
    units: list[str] = []
    for para in text.split("\n\n"):
        if len(para) <= MAX_CHUNK_CHARS:
            units.append(para)
        else:
            units.extend(re.split(r"(?<=[.!?])\s+(?=[A-Z])", para))
    parts, cur = [], ""
    for unit in units:
        if cur and len(cur) + len(unit) > MAX_CHUNK_CHARS:
            parts.append(cur.strip())
            cur = ""
        cur += unit + ("\n\n" if unit in text.split("\n\n") else " ")
    if cur.strip():
        parts.append(cur.strip())
    return parts


def _sections(body: str) -> list[tuple[str, str]]:
    """(section label, text) pairs, cut at ## then ###.

    A ### section is labelled "H2 > H3". "Related"-like sections are dropped,
    "Contact us" is kept whole.
    """
    out: list[tuple[str, str]] = []
    h2, h3, buf = "Introduction", None, []

    def flush():
        text = "\n".join(buf).strip()
        if text and h2.lower() not in SKIPPED_SECTIONS:
            out.append((h2 if h3 is None else f"{h2} > {h3}", text))
        buf.clear()

    for line in body.splitlines():
        if line.startswith("## "):
            flush()
            h2, h3 = line[3:].strip(), None
        elif line.startswith("### ") and h2.lower() not in SINGLE_CHUNK_SECTIONS:
            flush()
            h3 = line[4:].strip()
        else:
            buf.append(line)
    flush()
    return out


def load_chunks(docs_dir: Path | None = None) -> list[Chunk]:
    docs_dir = Path(docs_dir or config.CITY_DOCS_DIR)
    chunks: list[Chunk] = []
    for path in sorted(docs_dir.glob("*.md")):
        meta, body = parse_front_matter(path.read_text(encoding="utf-8"))
        if not meta.get("url") or not meta.get("title"):
            continue  # a page without its source is never indexed
        doc_id = meta.get("doc_id", path.stem)
        page_type, body = split_page_header(body)
        n = 0
        for section, text in _sections(body):
            for part in _split_long(text):
                if len(part) < 40:
                    continue
                chunks.append(
                    Chunk(
                        chunk_id=f"{doc_id}#{n}",
                        doc_id=doc_id,
                        title=meta["title"],
                        url=meta["url"],
                        section=section,
                        page_type=page_type,
                        text=f"{meta['title']} — {section}\n{part}",
                    )
                )
                n += 1
    return chunks


# --------------------------------------------------------------- embeddings
class LocalHashEmbedder:
    """Deterministic bag-of-words hashing embedder (offline fallback only)."""

    name = "local"
    dim = 512

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * self.dim
        for tok in re.findall(r"\w+", text.lower()):
            if len(tok) < 3:
                continue
            h = int(hashlib.md5(tok[:7].encode()).hexdigest(), 16)
            v[h % self.dim] += 1.0
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(text)


class GeminiEmbedder:
    """Gemini embeddings (AI Studio key or Google Cloud / Vertex via ADC)."""

    name = "gemini"

    def __init__(self, model: str | None = None):
        from google import genai

        self.model = model or config.EMBEDDING_MODEL
        self.client = genai.Client()

    def _embed(self, texts: list[str], task: str) -> list[list[float]]:
        from google.genai import types

        out: list[list[float]] = []
        for i in range(0, len(texts), 50):
            resp = self.client.models.embed_content(
                model=self.model,
                contents=texts[i : i + 50],
                config=types.EmbedContentConfig(task_type=task),
            )
            out.extend(e.values for e in resp.embeddings)
        return out

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embed(texts, "RETRIEVAL_DOCUMENT")

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text], "RETRIEVAL_QUERY")[0]


def get_embedder():
    provider = os.getenv("RAG_EMBEDDINGS", "auto")
    if provider == "local" or (provider == "auto" and not config.gemini_configured()):
        return LocalHashEmbedder()
    return GeminiEmbedder()


# ------------------------------------------------------------------- index
class CityDocsIndex:
    def __init__(
        self,
        persist_dir: Path | None = None,
        embedder=None,
        docs_dir: Path | None = None,
    ):
        import chromadb

        self.embedder = embedder or get_embedder()
        self.docs_dir = docs_dir
        self.client = chromadb.PersistentClient(
            path=str(persist_dir or config.CHROMA_DIR)
        )
        self.collection = self.client.get_or_create_collection(
            name=f"city_docs_{self.embedder.name}", metadata={"hnsw:space": "cosine"}
        )

    def build(self, force: bool = False) -> int:
        chunks = load_chunks(self.docs_dir)
        current = self.collection.get(include=["documents"])
        stored = dict(zip(current["ids"], current["documents"], strict=True))
        if not force and stored == {c.chunk_id: c.text for c in chunks}:
            return len(chunks)  # index already up to date with the corpus
        existing = current["ids"]
        if existing:
            self.collection.delete(ids=existing)
        if chunks:
            self.collection.add(
                ids=[c.chunk_id for c in chunks],
                documents=[c.text for c in chunks],
                embeddings=self.embedder.embed_documents([c.text for c in chunks]),
                metadatas=[
                    {
                        "doc_id": c.doc_id,
                        "title": c.title,
                        "url": c.url,
                        "section": c.section,
                        "page_type": c.page_type,
                    }
                    for c in chunks
                ],
            )
        return len(chunks)

    def search(self, question: str, k: int = TOP_K) -> list[dict[str, Any]]:
        if self.collection.count() == 0:
            return []
        res = self.collection.query(
            query_embeddings=[self.embedder.embed_query(question)],
            n_results=min(k, self.collection.count()),
        )
        floor = MIN_SCORE.get(self.embedder.name, 0.0)
        hits = []
        for doc, meta, dist in zip(
            res["documents"][0], res["metadatas"][0], res["distances"][0], strict=True
        ):
            score = round(1 - float(dist), 3)
            if score >= floor:
                hits.append(
                    {
                        "doc_id": meta["doc_id"],
                        "title": meta["title"],
                        "url": meta["url"],
                        "section": meta["section"],
                        "page_type": meta.get("page_type", ""),
                        "score": score,
                        "text": doc,
                    }
                )
        return hits


@lru_cache(maxsize=1)
def get_index() -> CityDocsIndex:
    idx = CityDocsIndex()
    idx.build()
    return idx


def search_city_docs(question: str) -> dict[str, Any]:
    """Search the official City of San Francisco pages (DBI, Planning) about permit
    requirements for residential work (kitchen, bathroom, ADU, reroofing, solar, windows).

    Returns up to 3 relevant passages, each with its source title and URL, which MUST
    be cited in the answer. If no relevant passage exists, says so: do not answer
    from memory in that case.

    Args:
        question: the requirement you look for, ideally in English, e.g.
            "documents required for an ADU building permit".
    """
    from pydantic import ValidationError

    from app.schemas import QuestionArgs

    try:
        args = QuestionArgs(question=question)
    except ValidationError as exc:
        return {"error": "INVALID_INPUT", "message": str(exc)}
    index = get_index()
    if index.collection.count() == 0:
        return {
            "error": "CORPUS_EMPTY",
            "message": "Aucun document officiel n'est indexé.",
        }
    hits = index.search(args.question)
    if not hits:
        return {
            "question": args.question,
            "passages": [],
            "status": "NO_RELEVANT_DOCUMENT",
            "message": "Aucun passage pertinent dans les documents officiels indexés. "
            "Ne pas répondre de mémoire : le dire à l'utilisateur.",
        }
    return {"question": args.question, "passages": hits}


if __name__ == "__main__":
    n = CityDocsIndex().build(force=True)
    print(f"Indexed {n} chunks into {config.CHROMA_DIR}")
