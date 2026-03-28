"""Routes memory reads/writes between mem0 and local store with dedup and sync.

Fixes applied:
- 2.2: Added threading.Lock() around all _pending_sync mutations to prevent race conditions.
- 2.14: Only remove items from _pending_sync after confirmed successful sync.
- 7.2: Sanitize text before storage to strip prompt-injection patterns.
"""

from __future__ import annotations

from collections import defaultdict
import hashlib
import re
import threading

try:
    from rank_bm25 import BM25Okapi
except Exception:  # pragma: no cover
    BM25Okapi = None

from core.memory.local_store import LocalMemoryStore
from core.memory.mem0_client import Mem0Client


from core.think.reasoning import detect_prompt_injection

_MAX_MEMORY_TEXT_LEN = 4000  # cap memory entries to prevent runaway growth


def _sanitize_memory_text(text: str) -> str:
    """Strip or truncate suspicious injection content before persisting."""
    truncated = text[:_MAX_MEMORY_TEXT_LEN]
    detected = detect_prompt_injection(truncated)
    if isinstance(detected, tuple):
        is_injected, reason = bool(detected[0]), str(detected[1] or "injection_detected")
    else:
        is_injected, reason = bool(detected), "injection_detected"
    if is_injected:
        return f"[filtered] memory injection: {reason}"
    return truncated


class MemoryRouter:
    def __init__(self, mem0: Mem0Client, local: LocalMemoryStore):
        self.mem0 = mem0
        self.local = local
        self._online = True
        self._pending_sync: dict[str, list[dict]] = defaultdict(list)
        self._seen_hashes: set[str] = set()
        self._sync_lock = threading.Lock()  # fix 2.2

    @property
    def online(self) -> bool:
        return self._online

    def set_online(self, online: bool) -> None:
        self._online = online

    def add(self, text: str, session_id: str, metadata: dict | None = None) -> dict:
        safe_text = _sanitize_memory_text(text)  # fix 7.2
        hash_id = hashlib.sha256(f"{session_id}:{safe_text}".encode("utf-8")).hexdigest()

        with self._sync_lock:  # fix 2.2: lock before mutating shared state
            if hash_id in self._seen_hashes:
                return {"status": "duplicate", "id": hash_id}

        local_result = self.local.add(safe_text, session_id, metadata)
        if local_result.get("status") in {"ok", "duplicate"}:
            with self._sync_lock:
                self._seen_hashes.add(hash_id)

        if self._online:
            self.mem0.add(safe_text, session_id, metadata)
        else:
            with self._sync_lock:
                self._pending_sync[session_id].append({"text": safe_text, "metadata": metadata or {}})

        return local_result

    def sync_pending(self, session_id: str) -> int:
        """Sync pending items for a session. Only removes items after successful sync (fix 2.14)."""
        if not self._online:
            return 0

        with self._sync_lock:
            items = list(self._pending_sync.get(session_id, []))

        synced = []
        failed = []
        for item in items:
            try:
                result = self.mem0.add(item["text"], session_id, item["metadata"])
                if result is not None:
                    synced.append(item)
                else:
                    failed.append(item)
            except Exception:
                failed.append(item)

        with self._sync_lock:
            # Keep only items that failed — remove successfully synced ones
            self._pending_sync[session_id] = failed

        return len(synced)

    def sync_all_pending(self) -> int:
        """Sync all sessions. Thread-safe snapshot of keys before iterating (fix 2.2)."""
        if not self._online:
            return 0
        with self._sync_lock:
            session_ids = list(self._pending_sync.keys())
        total = 0
        for session_id in session_ids:
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
