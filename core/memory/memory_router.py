"""Routes memory reads/writes between mem0 and local store with dedup and sync."""

from __future__ import annotations

from collections import defaultdict
import hashlib

try:
    from rank_bm25 import BM25Okapi
except Exception:  # pragma: no cover - fallback for minimal environments
    BM25Okapi = None

from core.memory.local_store import LocalMemoryStore
from core.memory.mem0_client import Mem0Client


class MemoryRouter:
    def __init__(self, mem0: Mem0Client, local: LocalMemoryStore):
        self.mem0 = mem0
        self.local = local
        self._online = True
        self._pending_sync: dict[str, list[dict]] = defaultdict(list)
        self._seen_hashes: set[str] = set()

    @property
    def online(self) -> bool:
        return self._online

    def set_online(self, online: bool) -> None:
        self._online = online

    def add(self, text: str, session_id: str, metadata: dict | None = None) -> dict:
        hash_id = hashlib.sha256(f"{session_id}:{text}".encode("utf-8")).hexdigest()
        if hash_id in self._seen_hashes:
            return {"status": "duplicate", "id": hash_id}

        self._seen_hashes.add(hash_id)
        local_result = self.local.add(text, session_id, metadata)

        if self._online:
            self.mem0.add(text, session_id, metadata)
        else:
            self._pending_sync[session_id].append({"text": text, "metadata": metadata or {}})

        return local_result

    def sync_pending(self, session_id: str) -> int:
        if not self._online:
            return 0
        items = self._pending_sync.get(session_id, [])
        for item in items:
            self.mem0.add(item["text"], session_id, item["metadata"])
        count = len(items)
        self._pending_sync[session_id] = []
        return count

    def sync_all_pending(self) -> int:
        if not self._online:
            return 0
        total = 0
        for session_id in list(self._pending_sync):
            total += self.sync_pending(session_id)
        return total

    def search(self, query: str, session_id: str, top_k: int = 5) -> list[dict]:
        vector_candidates = self.local.search(query, session_id, top_k=20)
        if not vector_candidates:
            return []

        if BM25Okapi is None:
            return vector_candidates[:top_k]

        corpus = [c["text"].split() for c in vector_candidates]
        bm25 = BM25Okapi(corpus)
        bm25_scores = bm25.get_scores(query.split())

        bm25_order = sorted(
            range(len(bm25_scores)),
            key=lambda i: bm25_scores[i],
            reverse=True,
        )
        bm25_rank_by_idx = {candidate_idx: rank + 1 for rank, candidate_idx in enumerate(bm25_order)}

        fused = []
        for idx, candidate in enumerate(vector_candidates):
            semantic_rank = idx + 1
            bm25_rank = bm25_rank_by_idx.get(idx, len(vector_candidates))
            rrf = (1 / (60 + semantic_rank)) + (1 / (60 + bm25_rank))
            fused.append((rrf, candidate))

        fused.sort(key=lambda x: x[0], reverse=True)
        return [item for _, item in fused[:top_k]]

    def get_all(self, session_id: str) -> list[dict]:
        return self.local.get_all(session_id)
