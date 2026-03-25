"""Subsystem heartbeat registry."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import threading
import time
from typing import Callable


@dataclass
class HealthItem:
    name: str
    status: str
    last_heartbeat: str


class HealthMonitor:
    def __init__(self):
        self._state: dict[str, HealthItem] = {}
        self._checks: dict[str, tuple[Callable[[], bool], Callable[[], None] | None]] = {}
        self._lock = threading.Lock()
        self._running = False
        self._thread: threading.Thread | None = None

    def heartbeat(self, name: str, status: str = "ok") -> None:
        with self._lock:
            self._state[name] = HealthItem(
                name=name,
                status=status,
                last_heartbeat=datetime.now().isoformat(timespec="seconds"),
            )

    def register_subsystem(
        self,
        name: str,
        check_fn: Callable[[], bool],
        restart_fn: Callable[[], None] | None = None,
    ) -> None:
        self._checks[name] = (check_fn, restart_fn)
        self.heartbeat(name, "unknown")

    def poll_once(self) -> None:
        for name, (check_fn, restart_fn) in self._checks.items():
            try:
                healthy = bool(check_fn())
            except Exception:
                healthy = False
            if healthy:
                self.heartbeat(name, "ok")
                continue

            self.heartbeat(name, "down")
            if restart_fn is not None:
                try:
                    restart_fn()
                    self.heartbeat(name, "restarting")
                except Exception:
                    self.heartbeat(name, "restart_failed")

    def start(self, interval_seconds: int = 60) -> None:
        if self._running:
            return
        self._running = True

        def _loop() -> None:
            while self._running:
                self.poll_once()
                time.sleep(interval_seconds)

        self._thread = threading.Thread(target=_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

    def status_table(self) -> list[dict]:
        with self._lock:
            return [item.__dict__ for item in self._state.values()]
