"""RAG over the bank's internal procedures (fictitious documents).

Pipeline: markdown files -> chunks (one per ``##`` section) -> embeddings
(Gemini ``gemini-embedding-001``) -> Chroma (local persistent vector store)
-> top-3 passages **with their source** (procedure id + section).

If no Gemini backend is configured (CI, offline unit tests), a deterministic
local hashing embedder is used instead so the pipeline stays testable. The
provider is part of the collection name, so the two never mix.
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from app import config

PROC_ID_RE = re.compile(r"^(PROC-\d{2})")
TOP_K = 3


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    procedure_id: str
    title: str
    section: str
    source: str
    text: str


# ----------------------------------------------------------------- chunking
def load_chunks(proc_dir: Path | None = None) -> list[Chunk]:
    proc_dir = Path(proc_dir or config.PROCEDURES_DIR)
    chunks: list[Chunk] = []
    for path in sorted(proc_dir.glob("PROC-*.md")):
        m = PROC_ID_RE.match(path.name)
        if not m:
            continue
        proc_id = m.group(1)
        raw = path.read_text(encoding="utf-8")
        lines = raw.splitlines()
        title = lines[0].lstrip("# ").strip() if lines else proc_id
        body = "\n".join(lines[1:])
        # Drop the "document fictif" disclaimer lines from the indexed text.
        body = "\n".join(line for line in body.splitlines() if not line.startswith(">"))
        sections = re.split(r"^## ", body, flags=re.MULTILINE)
        for i, sec in enumerate(sections):
            sec = sec.strip()
            if not sec:
                continue
            if i == 0:
                name, text = "Introduction", sec
            else:
                name, _, text = sec.partition("\n")
                text = text.strip()
            chunks.append(
                Chunk(
                    chunk_id=f"{proc_id}#{i}",
                    procedure_id=proc_id,
                    title=title,
                    section=name.strip(),
                    source=path.name,
                    # Title is prepended so each chunk is self-describing.
                    text=f"{title} — {name.strip()}\n{text}",
                )
            )
    return chunks


@lru_cache(maxsize=1)
def known_procedure_ids() -> frozenset[str]:
    return frozenset(c.procedure_id for c in load_chunks())


def procedure_exists(procedure_id: str) -> bool:
    return procedure_id in known_procedure_ids()


# --------------------------------------------------------------- embeddings
class LocalHashEmbedder:
    """Deterministic bag-of-words hashing embedder (offline fallback only)."""

    name = "local"
    dim = 512

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * self.dim
        tokens = re.findall(r"\w+", text.lower())
        for tok in tokens:
            if len(tok) < 3:
                continue
            tok = tok[
                :6
            ]  # crude stemming: bloquer/blocage/bloquée -> "bloque"/"blocag"
            h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
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
    import os

    provider = os.getenv("RAG_EMBEDDINGS", "auto")
    if provider == "local" or (provider == "auto" and not config.gemini_configured()):
        return LocalHashEmbedder()
    return GeminiEmbedder()


# ------------------------------------------------------------------- index
class ProcedureIndex:
    def __init__(self, persist_dir: Path | None = None, embedder=None):
        import chromadb

        self.embedder = embedder or get_embedder()
        self.client = chromadb.PersistentClient(
            path=str(persist_dir or config.CHROMA_DIR)
        )
        self.collection = self.client.get_or_create_collection(
            name=f"procedures_{self.embedder.name}", metadata={"hnsw:space": "cosine"}
        )

    def build(self, force: bool = False) -> int:
        chunks = load_chunks()
        if self.collection.count() == len(chunks) and not force:
            return len(chunks)
        existing = self.collection.get()["ids"]
        if existing:
            self.collection.delete(ids=existing)
        self.collection.add(
            ids=[c.chunk_id for c in chunks],
            documents=[c.text for c in chunks],
            embeddings=self.embedder.embed_documents([c.text for c in chunks]),
            metadatas=[
                {
                    "procedure_id": c.procedure_id,
                    "title": c.title,
                    "section": c.section,
                    "source": c.source,
                }
                for c in chunks
            ],
        )
        return len(chunks)

    def search(self, question: str, k: int = TOP_K) -> list[dict[str, Any]]:
        if self.collection.count() == 0:
            self.build()
        res = self.collection.query(
            query_embeddings=[self.embedder.embed_query(question)], n_results=k
        )
        hits = []
        for doc, meta, dist in zip(
            res["documents"][0], res["metadatas"][0], res["distances"][0], strict=True
        ):
            hits.append(
                {
                    "procedure_id": meta["procedure_id"],
                    "title": meta["title"],
                    "section": meta["section"],
                    "source": meta["source"],
                    "score": round(1 - float(dist), 3),
                    "text": doc,
                }
            )
        return hits


@lru_cache(maxsize=1)
def get_index() -> ProcedureIndex:
    idx = ProcedureIndex()
    idx.build()
    return idx


def search_procedures(question: str) -> dict[str, Any]:
    """Search the bank's internal fraud procedures (RAG).

    Returns the 3 most relevant passages, each with its source
    (procedure_id, title, section). The answer MUST cite the procedure_id used.

    Args:
        question: What you need to know, e.g. "quand bloquer une carte ?".
    """
    from pydantic import ValidationError

    from app.schemas import SearchArgs

    try:
        args = SearchArgs(question=question)
    except ValidationError as exc:
        return {"error": "INVALID_INPUT", "message": str(exc)}
    return {"question": args.question, "passages": get_index().search(args.question)}


if __name__ == "__main__":
    n = ProcedureIndex().build(force=True)
    print(f"Indexed {n} chunks into {config.CHROMA_DIR}")
