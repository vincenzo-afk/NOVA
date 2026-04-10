"""Document vector store with ChromaDB and graceful fallback."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Any

from core.think.reasoning import detect_prompt_injection
from rag.chunker import chunk_text
from rag.doc_loader import DocumentLoader
from utils.embeddings import EmbeddingBackend, get_embedder


@dataclass
class StoredChunk:
    text: str
    metadata: dict[str, Any]


class DocumentStore:
    def __init__(
        self,
        persist_dir: str = ".jarvis_docs",
        collection_name: str = "jarvis_docs",
        embedding_model: str = "all-MiniLM-L6-v2",
    ):
        self.loader = DocumentLoader()
        self._docs: dict[str, list[StoredChunk]] = {}
        self._doc_meta: dict[str, dict[str, Any]] = {}
        self.persist_dir = Path(persist_dir)
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self.collection_name = collection_name
        self.embedding_model = embedding_model
        self._client = None
        self._collection = None
        self._embedder: EmbeddingBackend | None = None
        self._chroma_retry_time = 0.0
        self._use_chroma = self._init_chroma()

    def _init_chroma(self) -> bool:
        try:
            import chromadb  # type: ignore

            if not EmbeddingBackend.is_available():
                return False
            import os
            host = os.getenv("CHROMA_HOST")
            port = os.getenv("CHROMA_PORT")
            if host and port:
                self._client = chromadb.HttpClient(host=host, port=port)
            else:
                self._client = chromadb.PersistentClient(path=str(self.persist_dir))
            self._collection = self._client.get_or_create_collection(
                self.collection_name,
                metadata={"hnsw:space": "cosine"},
            )
            self._embedder = get_embedder(self.embedding_model)
            return True
        except Exception:  # pragma: no cover - optional dependency
            return False

    def _chunk_id(self, filename: str, idx: int, text: str) -> str:
        seed = f"{filename}:{idx}:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"
        return hashlib.sha256(seed.encode("utf-8")).hexdigest()

    def ingest(self, filepath: str) -> dict:
        import time

        if not self._use_chroma and time.time() > self._chroma_retry_time:
            self._use_chroma = self._init_chroma()
            if not self._use_chroma:
                self._chroma_retry_time = time.time() + 60.0
        doc = self.loader.load(filepath)
        chunks = chunk_text(doc["text"])
        filename = doc["filename"]
        self._doc_meta[filename] = {
            "filepath": doc["filepath"],
            "modified_at": doc["modified_at"],
            "page_count": doc["page_count"],
            "size_bytes": doc["size_bytes"],
        }
        self._docs[filename] = []
        for idx, chunk in enumerate(chunks):
            meta = {
                "filename": filename,
                "chunk_index": idx,
                **self._doc_meta[filename],
            }
            self._docs[filename].append(StoredChunk(text=chunk, metadata=meta))

        # Fix 1.8: Check disk space before writing
        if self._use_chroma:
            try:
                import shutil
                usage = shutil.disk_usage(str(self.persist_dir))
                # Warn if less than 1 GB free
                if usage.free < 1_000_000_000:
                    try:
                        from utils.logger import get_logger
                        get_logger(__name__).warning(
                            f"Low disk space ({usage.free / 1e9:.1f} GB free) — ChromaDB may fail"
                        )
                    except Exception:
                        pass
            except Exception:
                pass

        if self._use_chroma and self._collection and self._embedder:
            try:
                texts = [c.text for c in self._docs[filename]]
                embeddings = []
                batch_size = 64
                for i in range(0, len(texts), batch_size):
                    embeddings.extend(self._embedder.encode(texts[i : i + batch_size]))
                ids = [self._chunk_id(filename, idx, c.text) for idx, c in enumerate(self._docs[filename])]
                self._collection.upsert(
                    ids=ids,
                    documents=texts,
                    metadatas=[c.metadata for c in self._docs[filename]],
                    embeddings=embeddings,
                )
            except Exception:
                # Fix 2.8: Log warning when ChromaDB degrades
                try:
                    from utils.logger import get_logger
                    get_logger(__name__).warning(
                        "ChromaDB failed during ingest — falling back to in-memory keyword search. "
                        "Previously stored documents will be inaccessible until restart."
                    )
                except Exception:
                    pass
                self._use_chroma = False
                self._chroma_retry_time = time.time() + 60.0
        return {"filename": filename, "chunks": len(chunks), **self._doc_meta[filename]}

    def query(self, question: str, filename: str | None = None, top_k: int = 5) -> list[str]:
        def _sanitize_chunks(chunks: list[str]) -> list[str]:
            out: list[str] = []
            for chunk in chunks:
                if not chunk:
                    continue
                if detect_prompt_injection(chunk):
                    continue
                out.append("[Content from document (unverified)]\n" + chunk)
            return out

        if self._use_chroma and self._collection and self._embedder:
            try:
                embedding = self._embedder.encode([question])[0]
                query_kwargs = {"query_embeddings": [embedding], "n_results": top_k}
                if filename:
                    query_kwargs["where"] = {"filename": filename}
                results = self._collection.query(**query_kwargs)
                docs = results.get("documents", [[]])[0]
                return _sanitize_chunks([doc for doc in docs if doc])
            except Exception:
                self._use_chroma = False

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
        return _sanitize_chunks([text for _, text in scored[:top_k]])

    def list_docs(self) -> list[dict[str, Any]]:
        return [
            {"filename": name, **self._doc_meta.get(name, {})}
            for name in sorted(self._docs.keys())
        ]

    def delete(self, filename: str) -> dict[str, Any]:
        removed = False
        chunks = self._docs.pop(filename, [])
        self._doc_meta.pop(filename, None)
        if chunks:
            removed = True
        if self._use_chroma and self._collection:
            try:
                # Delete by filename metadata to avoid stale/changing chunk-id mismatches.
                self._collection.delete(where={"filename": filename})
            except Exception:
                self._use_chroma = False
        return {"status": "ok" if removed else "not_found", "filename": filename}

    def update(self, filepath: str) -> dict[str, Any]:
        filename = Path(filepath).name
        self.delete(filename)
        return self.ingest(filepath)
