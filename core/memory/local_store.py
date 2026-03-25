"""Local Chroma-like store with graceful in-memory fallback."""

from __future__ import annotations

import hashlib
from pathlib import Path


class LocalMemoryStore:
    def __init__(self, persist_dir: str = ".jarvis_chroma"):
        self.persist_dir = Path(persist_dir)
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self._items: list[dict] = []

    def add(self, text: str, session_id: str, metadata: dict | None = None) -> dict:
        hash_id = hashlib.sha256(f"{session_id}:{text}".encode("utf-8")).hexdigest()
        if any(i["id"] == hash_id for i in self._items):
            return {"status": "duplicate", "id": hash_id}
        self._items.append(
            {
                "id": hash_id,
                "text": text,
                "session_id": session_id,
                "metadata": metadata or {},
            }
        )
        return {"status": "ok", "id": hash_id}

    def search(self, query: str, session_id: str, top_k: int = 20) -> list[dict]:
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
        return [
            {"id": i["id"], "text": i["text"], "metadata": i["metadata"]}
            for i in self._items
            if i["session_id"] == session_id
        ]
