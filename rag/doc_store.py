"""Document vector-like store built on local memory primitives."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rag.chunker import chunk_text
from rag.doc_loader import DocumentLoader


@dataclass
class StoredChunk:
    text: str
    metadata: dict[str, Any]


class DocumentStore:
    def __init__(self):
        self.loader = DocumentLoader()
        self._docs: dict[str, list[StoredChunk]] = {}
        self._doc_meta: dict[str, dict[str, Any]] = {}

    def ingest(self, filepath: str) -> dict:
        doc = self.loader.load(filepath)
        chunks = chunk_text(doc["text"])
        filename = doc["filename"]
        self._doc_meta[filename] = {
            "filepath": doc["filepath"],
            "modified_at": doc["modified_at"],
            "page_count": doc["page_count"],
            "size_bytes": doc["size_bytes"],
        }
        self._docs[filename] = [
            StoredChunk(
                text=chunk,
                metadata={
                    "filename": filename,
                    "chunk_index": idx,
                    **self._doc_meta[filename],
                },
            )
            for idx, chunk in enumerate(chunks)
        ]
        return {"filename": filename, "chunks": len(chunks), **self._doc_meta[filename]}

    def query(self, question: str, filename: str | None = None, top_k: int = 5) -> list[str]:
        corpus: list[StoredChunk] = []
        if filename:
            corpus = self._docs.get(filename, [])
        else:
            for chunks in self._docs.values():
                corpus.extend(chunks)

        q_terms = set(question.lower().split())
        scored = []
        for chunk in corpus:
            score = len(q_terms & set(chunk.text.lower().split()))
            if score:
                scored.append((score, chunk.text))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [text for _, text in scored[:top_k]]

    def list_docs(self) -> list[dict[str, Any]]:
        return [
            {"filename": name, **self._doc_meta.get(name, {})}
            for name in sorted(self._docs.keys())
        ]
