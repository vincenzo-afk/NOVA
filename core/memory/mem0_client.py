"""mem0 client wrapper with optional remote support and local fallback."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import time
from typing import Any


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
        self._client: Any | None = None
        self._remote_enabled = False
        self._init_remote()

    def _init_remote(self) -> None:
        if not self.api_key:
            return
        # Try multiple possible SDKs/clients (mem0 is evolving).
        last_exc: Exception | None = None
        for module_name, ctor_name in (
            ("mem0ai", "MemoryClient"),
            ("mem0ai", "Client"),
            ("mem0", "Memory"),
            ("mem0", "Client"),
        ):
            try:
                module = __import__(module_name, fromlist=[ctor_name])
                ctor = getattr(module, ctor_name, None)
                if ctor is None:
                    continue
                self._client = ctor(api_key=self.api_key)
                self._remote_enabled = True
                return
            except Exception as exc:
                last_exc = exc
                continue
        try:
            from utils.logger import get_logger
            get_logger(__name__).warning(
                "mem0 remote init failed; using local fallback only: %s",
                last_exc,
            )
        except Exception:
            import logging
            logging.getLogger(__name__).warning(
                "mem0 remote init failed; using local fallback only: %s",
                last_exc,
            )

    @staticmethod
    def _call_with_variants(fn, **kwargs):
        """Call SDK method with fallback argument names."""
        variants = [
            kwargs,
            {**kwargs, "user_id": kwargs.get("session_id")},
            {**kwargs, "user_id": kwargs.get("session_id"), "memory": kwargs.get("text")},
            {**kwargs, "user_id": kwargs.get("session_id"), "content": kwargs.get("text")},
        ]
        last_signature_error: Exception | None = None
        for payload in variants:
            payload = {k: v for k, v in payload.items() if v is not None}
            try:
                return fn(**payload)
            except ConnectionError:
                raise
            except TimeoutError:
                raise
            except (TypeError, AttributeError) as exc:
                last_signature_error = exc
                time.sleep(0.05)
                continue
        raise TypeError(
            f"mem0 SDK call failed for all argument variants. "
            f"Tried keys: {[sorted([k for k, v in p.items() if v is not None]) for p in variants]}"
        ) from last_signature_error

    def add(self, text: str, session_id: str, metadata: dict | None = None) -> dict:
        if self._remote_enabled and self._client is not None:
            try:
                result = self._call_with_variants(
                    self._client.add,
                    text=text,
                    memory=text,
                    session_id=session_id,
                    metadata=metadata or {},
                )
                return {"status": "ok", "result": result}
            except Exception:
                # fall back to local cache
                pass

        payload = metadata or {}
        hash_id = hashlib.sha256(f"{session_id}:{text}".encode("utf-8")).hexdigest()
        if any(item.hash_id == hash_id for item in self._items):
            return {"status": "duplicate", "id": hash_id}
        item = MemoryItem(text=text, session_id=session_id, metadata=payload, hash_id=hash_id)
        self._items.append(item)
        return {"status": "ok", "id": hash_id}

    def search(self, query: str, session_id: str, top_k: int = 5) -> list[dict]:
        if self._remote_enabled and self._client is not None:
            try:
                raw = self._call_with_variants(
                    self._client.search,
                    query=query,
                    session_id=session_id,
                    top_k=top_k,
                )
                return self._normalize_search(raw)
            except Exception:
                pass

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
        if self._remote_enabled and self._client is not None:
            try:
                raw = self._call_with_variants(self._client.get_all, session_id=session_id)
                return self._normalize_list(raw)
            except Exception:
                pass

        return [
            {"text": item.text, "metadata": item.metadata, "id": item.hash_id}
            for item in self._items
            if item.session_id == session_id
        ]

    def _normalize_search(self, raw: Any) -> list[dict]:
        items = self._unwrap_items(raw)
        normalized = []
        for item in items:
            if isinstance(item, str):
                normalized.append({"text": item, "metadata": {}, "score": 0.0})
                continue
            if not isinstance(item, dict):
                continue
            text = item.get("text") or item.get("memory") or item.get("content") or ""
            meta = item.get("metadata") or item.get("meta") or {}
            score = item.get("score") or item.get("similarity") or 0.0
            normalized.append({"text": text, "metadata": meta, "score": score})
        return normalized

    def _normalize_list(self, raw: Any) -> list[dict]:
        items = self._unwrap_items(raw)
        output = []
        for item in items:
            if isinstance(item, str):
                output.append({"text": item, "metadata": {}})
                continue
            if not isinstance(item, dict):
                continue
            text = item.get("text") or item.get("memory") or item.get("content") or ""
            meta = item.get("metadata") or item.get("meta") or {}
            item_id = item.get("id") or item.get("memory_id") or ""
            output.append({"text": text, "metadata": meta, "id": item_id})
        return output

    @staticmethod
    def _unwrap_items(raw: Any) -> list[Any]:
        if raw is None:
            return []
        if isinstance(raw, list):
            return raw
        if isinstance(raw, dict):
            for key in ("results", "memories", "data"):
                if key in raw and isinstance(raw[key], list):
                    return raw[key]
        return []
