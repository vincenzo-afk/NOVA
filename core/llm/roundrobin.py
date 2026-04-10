"""Round-robin key rotation with TTL cooldown and backoff recovery.

Fixes applied:
- 2.5: Cap backoff at MAX_BACKOFF_SECONDS (3600s = 1h) to prevent permanent dead keys.
- 2.1: Log a warning when a pool is created with zero active keys.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
import threading
from typing import Callable

MAX_BACKOFF_SECONDS = 3600  # fix 2.5: never back off more than 1 hour


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
        self._lock = threading.RLock()

        # fix 2.1: warn if pool has no usable keys
        if not self._keys:
            print("[WARNING] RoundRobinPool: no active cloud API keys configured")

    def _recover_due_keys(self) -> None:
        now = self._now_fn()
        for record in self._keys:
            if (
                record.status in {"rate_limited", "dead"}
                and record.cooldown_until is not None
                and now >= record.cooldown_until
            ):
                record.status = "active"
                record.cooldown_until = None
                record.failures = 0  # fix 2.5: reset failure count after recovery

    def get_next(self) -> str | None:
        with self._lock:
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
        with self._lock:
            record = self._find(key)
            record.status = "active"
            record.failures = 0
            record.cooldown_until = None

    def mark_dead(self, key: str) -> None:
        with self._lock:
            record = self._find(key)
            record.failures += 1
            record.status = "dead"
            record.cooldown_until = self._now_fn() + timedelta(seconds=MAX_BACKOFF_SECONDS)

    def mark_rate_limited(self, key: str, retry_after: int = 60) -> None:
        with self._lock:
            record = self._find(key)
            record.failures += 1
            raw_backoff = max(retry_after, 60) * (2 ** (record.failures - 1))
            # fix 2.5: cap backoff so keys are always recoverable within 1 hour max
            backoff = min(raw_backoff, MAX_BACKOFF_SECONDS)
            record.status = "rate_limited"
            record.cooldown_until = self._now_fn() + timedelta(seconds=backoff)

        try:
            label = self.key_label(key)
            logging.getLogger(__name__).warning(
                "Key %s is rate-limited (failure #%s); cooldown %ss (capped at %ss)",
                label,
                record.failures,
                backoff,
                MAX_BACKOFF_SECONDS,
            )
        except Exception:
            pass

    def key_label(self, key: str) -> str:
        with self._lock:
            for idx, record in enumerate(self._keys, start=1):
                if record.key == key:
                    return f"key_{idx}"
            return "unknown_key"

    def active_count(self) -> int:
        with self._lock:
            self._recover_due_keys()
            return sum(1 for k in self._keys if k.status == "active")

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            self._recover_due_keys()
            cloud = [
                {
                    "key": self.key_label(k.key),
                    "status": k.status,
                    "failures": k.failures,
                    "cooldown_until": k.cooldown_until.isoformat() if k.cooldown_until else None,
                }
                for k in self._keys
            ]
            return {"cloud": cloud, "active_count": sum(1 for k in self._keys if k.status == "active")}

    def _find(self, key: str) -> KeyState:
        for record in self._keys:
            if record.key == key:
                return record
        raise KeyError(f"Unknown key: {key}")
