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
    def __init__(self, on_change: Callable[[str, str, str | None], None] | None = None):
        self._state: dict[str, HealthItem] = {}
        self._checks: dict[str, tuple[Callable[[], bool], Callable[[], None] | None]] = {}
        self._lock = threading.Lock()
        self._running = False
        self._thread: threading.Thread | None = None
        self._on_change = on_change

    def heartbeat(self, name: str, status: str = "ok") -> None:
        with self._lock:
            self._state[name] = HealthItem(
                name=name,
                status=status,
                last_heartbeat=datetime.now().isoformat(timespec="seconds"),
            )

    def _emit_change(self, name: str, status: str, previous_status: str | None) -> None:
        if self._on_change is None:
            return
        if previous_status == status:
            return
        try:
            self._on_change(name, status, previous_status)
        except Exception:
            pass

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
            previous = self._state.get(name)
            previous_status = previous.status if previous is not None else None
            try:
                healthy = bool(check_fn())
            except Exception:
                healthy = False
            if healthy:
                self.heartbeat(name, "ok")
                self._emit_change(name, "ok", previous_status)
                continue

            self.heartbeat(name, "down")
            self._emit_change(name, "down", previous_status)
            if restart_fn is not None:
                try:
                    restart_fn()
                    self.heartbeat(name, "restarting")
                    self._emit_change(name, "restarting", "down")
                except Exception:
                    self.heartbeat(name, "restart_failed")
                    self._emit_change(name, "restart_failed", "down")

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
