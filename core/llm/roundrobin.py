"""Round-robin key rotation with TTL cooldown and backoff recovery."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable


@dataclass
class KeyState:
    key: str
    status: str = "active"  # active | rate_limited | dead
    failures: int = 0
    cooldown_until: datetime | None = None


class RoundRobinPool:
    def __init__(self, keys: list[str], now_fn: Callable[[], datetime] | None = None):
        self._keys = [KeyState(key=k) for k in keys if k.strip()]
        self._index = 0
        self._now_fn = now_fn or (lambda: datetime.now(timezone.utc))

    def _recover_due_keys(self) -> None:
        now = self._now_fn()
        for record in self._keys:
            if (
                record.status == "rate_limited"
                and record.cooldown_until is not None
                and now >= record.cooldown_until
            ):
                record.status = "active"
                record.cooldown_until = None

    def get_next(self) -> str | None:
        if not self._keys:
            return None
        self._recover_due_keys()
        total = len(self._keys)
        for _ in range(total):
            record = self._keys[self._index]
            self._index = (self._index + 1) % total
            if record.status == "active":
                return record.key
        return None

    def mark_success(self, key: str) -> None:
        record = self._find(key)
        record.status = "active"
        record.failures = 0
        record.cooldown_until = None

    def mark_dead(self, key: str) -> None:
        record = self._find(key)
        record.status = "dead"

    def mark_rate_limited(self, key: str, retry_after: int = 60) -> None:
        record = self._find(key)
        record.failures += 1
        backoff = max(retry_after, 60) * (2 ** (record.failures - 1))
        record.status = "rate_limited"
        record.cooldown_until = self._now_fn() + timedelta(seconds=backoff)

    def key_label(self, key: str) -> str:
        for idx, record in enumerate(self._keys, start=1):
            if record.key == key:
                return f"key_{idx}"
        return "unknown_key"

    def active_count(self) -> int:
        self._recover_due_keys()
        return sum(1 for k in self._keys if k.status == "active")

    def snapshot(self) -> list[dict]:
        self._recover_due_keys()
        return [
            {
                "key": self.key_label(k.key),
                "status": k.status,
                "failures": k.failures,
                "cooldown_until": k.cooldown_until.isoformat() if k.cooldown_until else None,
            }
            for k in self._keys
        ]

    def _find(self, key: str) -> KeyState:
        for record in self._keys:
            if record.key == key:
                return record
        raise KeyError(f"Unknown key: {key}")
