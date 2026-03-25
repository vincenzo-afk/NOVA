"""mem0 client wrapper with local fallback for development/testing."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib


@dataclass
class MemoryItem:
    text: str
    session_id: str
    metadata: dict
    hash_id: str


class Mem0Client:
    def __init__(self, api_key: str = ""):
        self.api_key = api_key
        self._items: list[MemoryItem] = []

    def add(self, text: str, session_id: str, metadata: dict | None = None) -> dict:
        payload = metadata or {}
        hash_id = hashlib.sha256(f"{session_id}:{text}".encode("utf-8")).hexdigest()
        if any(item.hash_id == hash_id for item in self._items):
            return {"status": "duplicate", "id": hash_id}
        item = MemoryItem(text=text, session_id=session_id, metadata=payload, hash_id=hash_id)
        self._items.append(item)
        return {"status": "ok", "id": hash_id}

    def search(self, query: str, session_id: str, top_k: int = 5) -> list[dict]:
        q = query.lower()
        scored = []
        for item in self._items:
            if item.session_id != session_id:
                continue
            score = len(set(q.split()) & set(item.text.lower().split()))
            if score > 0:
                scored.append((score, item))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            {"text": item.text, "metadata": item.metadata, "score": score}
            for score, item in scored[:top_k]
        ]

    def get_all(self, session_id: str) -> list[dict]:
        return [
            {"text": item.text, "metadata": item.metadata, "id": item.hash_id}
            for item in self._items
            if item.session_id == session_id
        ]
