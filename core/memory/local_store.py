"""Local ChromaDB-backed store with graceful in-memory fallback."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from utils.embeddings import EmbeddingBackend, get_embedder


class LocalMemoryStore:
    def __init__(
        self,
        persist_dir: str = ".jarvis_chroma",
        collection_name: str = "jarvis_memory",
        embedding_model: str = "all-MiniLM-L6-v2",
    ):
        self.persist_dir = Path(persist_dir)
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self.collection_name = collection_name
        self.embedding_model = embedding_model
        self._items: list[dict] = []
        self._item_hashes: set[str] = set()
        self._client = None
        self._collection = None
        self._embedder: EmbeddingBackend | None = None
        self._use_chroma = self._init_chroma()
        self._chroma_retry_time = 0.0

    def _init_chroma(self) -> bool:
        try:
            import chromadb  # type: ignore

            if not EmbeddingBackend.is_available():
                return False
            self._client = chromadb.PersistentClient(path=str(self.persist_dir))
            self._collection = self._client.get_or_create_collection(
                self.collection_name,
                metadata={"hnsw:space": "cosine"},
            )
            self._embedder = get_embedder(self.embedding_model)
            return True
        except Exception:  # pragma: no cover - optional dependency
            return False

    def _chroma_get(self, **kwargs) -> dict[str, Any]:
        if not self._collection:
            return {}
        return self._collection.get(**kwargs)

    def _chroma_query(self, **kwargs) -> dict[str, Any]:
        if not self._collection:
            return {}
        return self._collection.query(**kwargs)

    def _dedup_exists(self, hash_id: str) -> bool:
        import time
        if not self._use_chroma:
            if time.time() > self._chroma_retry_time:
                self._use_chroma = self._init_chroma()
            
        if not self._use_chroma:
            return hash_id in self._item_hashes
        try:
            data = self._chroma_get(ids=[hash_id])
            if data and data.get("ids"):
                return True
            return hash_id in self._item_hashes
        except Exception:
            self._use_chroma = False
            self._chroma_retry_time = time.time() + 60.0
            return hash_id in self._item_hashes

    def add(self, text: str, session_id: str, metadata: dict | None = None) -> dict:
        hash_id = hashlib.sha256(f"{session_id}:{text}".encode("utf-8")).hexdigest()
        if self._dedup_exists(hash_id):
            return {"status": "duplicate", "id": hash_id}

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

        payload = metadata or {}
        if self._use_chroma and self._collection and self._embedder:
            try:
                embedding = self._embedder.encode([text])[0]
                self._collection.add(
                    ids=[hash_id],
                    documents=[text],
                    metadatas=[{"session_id": session_id, **payload}],
                    embeddings=[embedding],
                )
                return {"status": "ok", "id": hash_id}
            except Exception:
                import time
                self._use_chroma = False
                self._chroma_retry_time = time.time() + 60.0

        self._items.append(
            {
                "id": hash_id,
                "text": text,
                "session_id": session_id,
                "metadata": payload,
            }
        )
        self._item_hashes.add(hash_id)
        return {"status": "ok", "id": hash_id}

    def search(self, query: str, session_id: str, top_k: int = 20) -> list[dict]:
        if self._use_chroma and self._collection and self._embedder:
            try:
                embedding = self._embedder.encode([query])[0]
                results = self._chroma_query(
                    query_embeddings=[embedding],
                    n_results=top_k,
                    where={"session_id": session_id},
                )
                ids = results.get("ids", [[]])[0]
                docs = results.get("documents", [[]])[0]
                metas = results.get("metadatas", [[]])[0]
                distances = results.get("distances", [[]])[0]
                output = []
                for idx, doc in enumerate(docs):
                    distance = distances[idx] if idx < len(distances) else None
                    score = float(1.0 - distance) if distance is not None else 0.0
                    output.append(
                        {
                            "id": ids[idx],
                            "text": doc,
                            "metadata": metas[idx] if idx < len(metas) else {},
                            "score": score,
                        }
                    )
                return output
            except Exception:
                import time
                self._use_chroma = False
                self._chroma_retry_time = time.time() + 60.0

        q_terms = set(query.lower().split())
        scored = []
        for item in self._items:
            if item["session_id"] != session_id:
                continue
            score = len(q_terms & set(item["text"].lower().split()))
            if score:
                scored.append((score, item))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            {"id": item["id"], "text": item["text"], "metadata": item["metadata"], "score": score}
            for score, item in scored[:top_k]
        ]

    def get_all(self, session_id: str) -> list[dict]:
        if self._use_chroma and self._collection:
            try:
                results = self._chroma_get(where={"session_id": session_id})
                ids = results.get("ids", [])
                docs = results.get("documents", [])
                metas = results.get("metadatas", [])
                return [
                    {"id": ids[idx], "text": docs[idx], "metadata": metas[idx]}
                    for idx in range(len(ids))
                ]
            except Exception:
                import time
                self._use_chroma = False
                self._chroma_retry_time = time.time() + 60.0

        return [
            {"id": i["id"], "text": i["text"], "metadata": i["metadata"]}
            for i in self._items
            if i["session_id"] == session_id
        ]
