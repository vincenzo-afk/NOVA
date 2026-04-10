"""Routes memory reads/writes between mem0 and local store with dedup and sync.

Fixes applied:
- 2.2: Added threading.Lock() around all _pending_sync mutations to prevent race conditions.
- 2.14: Only remove items from _pending_sync after confirmed successful sync.
- 7.2: Sanitize text before storage to strip prompt-injection patterns.
"""

from __future__ import annotations

from collections import defaultdict
from collections import deque
import hashlib
import json
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
    _MAX_SEEN_HASHES = 200_000

    def __init__(self, mem0: Mem0Client, local: LocalMemoryStore):
        self.mem0 = mem0
        self.local = local
        self._online = True
        self._remote_sync_enabled = True
        self._pending_sync: dict[str, list[dict]] = defaultdict(list)
        self._seen_hashes: set[str] = set()
        self._seen_hash_order: deque[str] = deque()
        self._sync_lock = threading.Lock()  # fix 2.2

    @property
    def online(self) -> bool:
        return self._online

    def set_online(self, online: bool) -> None:
        self._online = online

    def set_remote_sync_enabled(self, enabled: bool) -> None:
        with self._sync_lock:
            self._remote_sync_enabled = bool(enabled)

    def add(self, text: str, session_id: str, metadata: dict | None = None) -> dict:
        safe_text = _sanitize_memory_text(text)  # fix 7.2
        hash_id = hashlib.sha256(f"{session_id}:{safe_text}".encode("utf-8")).hexdigest()

        with self._sync_lock:  # fix 2.2: lock before mutating shared state
            if hash_id in self._seen_hashes:
                return {"status": "duplicate", "id": hash_id}
            # Reserve the hash before local I/O to avoid TOCTOU duplicates.
            self._seen_hashes.add(hash_id)
            self._seen_hash_order.append(hash_id)
            while len(self._seen_hash_order) > self._MAX_SEEN_HASHES:
                old = self._seen_hash_order.popleft()
                self._seen_hashes.discard(old)

        local_result = self.local.add(safe_text, session_id, metadata)
        if local_result.get("status") not in {"ok", "duplicate"}:
            with self._sync_lock:
                self._seen_hashes.discard(hash_id)
                try:
                    self._seen_hash_order.remove(hash_id)
                except ValueError:
                    pass
            return local_result

        if self._online and self._remote_sync_enabled:
            self.mem0.add(safe_text, session_id, metadata)
        elif self._remote_sync_enabled:
            with self._sync_lock:
                self._pending_sync[session_id].append({"text": safe_text, "metadata": metadata or {}})

        return local_result

    def sync_pending(self, session_id: str) -> int:
        """Sync pending items for a session. Only removes items after successful sync (fix 2.14)."""
        if not self._online or not self._remote_sync_enabled:
            return 0

        with self._sync_lock:
            original_items = list(self._pending_sync.get(session_id, []))

        synced = []
        for item in original_items:
            try:
                result = self.mem0.add(item["text"], session_id, item["metadata"])
                if isinstance(result, dict) and result.get("status") == "ok":
                    synced.append(item)
                else:
                    continue
            except Exception:
                continue

        with self._sync_lock:
            # Remove only items from the original snapshot that synced successfully.
            # Any items appended concurrently after snapshotting must be preserved.
            current_items = list(self._pending_sync.get(session_id, []))
            def _item_key(item: dict) -> str:
                text = str(item.get("text", ""))
                meta = item.get("metadata", {}) or {}
                return hashlib.sha256(
                    f"{session_id}:{text}:{json.dumps(meta, sort_keys=True, ensure_ascii=False)}".encode("utf-8")
                ).hexdigest()

            synced_keys = {_item_key(item) for item in synced}
            retained = [item for item in current_items if _item_key(item) not in synced_keys]
            self._pending_sync[session_id] = retained

        return len(synced)

    def sync_all_pending(self) -> int:
        """Sync all sessions. Thread-safe snapshot of keys before iterating (fix 2.2)."""
        if not self._online or not self._remote_sync_enabled:
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
        local_items = self.local.get_all(session_id)
        if self._online and self._remote_sync_enabled:
            try:
                remote_items = self.mem0.get_all(session_id)
                if remote_items:
                    seen = {i.get("text") for i in local_items if i.get("text")}
                    for r in remote_items:
                        t = r.get("text") or r.get("memory") or r.get("content") or ""
                        if t and t not in seen:
                            local_items.append({"text": t, "metadata": r.get("metadata", {}), "id": r.get("id", "")})
                            seen.add(t)
            except Exception:
                pass
        return local_items
