"""Proactive nudge engine for long-running task sessions (Phase 16)."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date
from typing import Callable


@dataclass
class NudgeState:
    task_key: str = ""
    started_at: float = 0.0
    last_seen_at: float = 0.0
    nudged_2h: bool = False
    nudged_4h: bool = False
    muted_for_day: str = ""  # ISO date


class NudgeEngine:
    def __init__(
        self,
        *,
        export_callback: Callable[[], str] | None = None,
    ):
        self._state = NudgeState()
        self._export_callback = export_callback

    def mute_today(self) -> None:
        self._state.muted_for_day = date.today().isoformat()

    def is_muted_today(self) -> bool:
        return self._state.muted_for_day == date.today().isoformat()

    def update_context(self, *, task_key: str, now_ts: float | None = None) -> None:
        now = now_ts or time.time()
        key = (task_key or "").strip().lower()
        if not key:
            return
        if self._state.task_key != key:
            self._state.task_key = key
            self._state.started_at = now
            self._state.last_seen_at = now
            self._state.nudged_2h = False
            self._state.nudged_4h = False
            return
        self._state.last_seen_at = now

    def detect_break(self, *, idle_seconds: float = 0.0, active_app: str = "", now_ts: float | None = None) -> bool:
        now = now_ts or time.time()
        app = (active_app or "").strip().lower()
        if idle_seconds >= 300:
            self._reset(now)
            return True
        # Approximate "break apps".
        if any(t in app for t in ("music", "spotify", "youtube", "netflix", "vlc")):
            self._reset(now)
            return True
        return False

    def maybe_nudge(self, *, now_ts: float | None = None) -> tuple[str, bool]:
        now = now_ts or time.time()
        if self.is_muted_today():
            return ("", False)
        if not self._state.task_key or self._state.started_at <= 0:
            return ("", False)
        elapsed_h = (now - self._state.started_at) / 3600.0
        if elapsed_h >= 4.0 and not self._state.nudged_4h:
            self._state.nudged_4h = True
            self._state.nudged_2h = True
            self._auto_export()
            return (
                "You've been on the same task for about 4 hours. "
                "Want me to save context and help you pause/resume later?",
                True,
            )
        if elapsed_h >= 2.0 and not self._state.nudged_2h:
            self._state.nudged_2h = True
            self._auto_export()
            return (
                "You've been focused on the same task for around 2 hours. "
                "Quick break reminder: stretch, water, and reset for 2 minutes?",
                False,
            )
        return ("", False)

    def _auto_export(self) -> None:
        if self._export_callback is None:
            return
        try:
            self._export_callback()
        except Exception:
            pass

    def _reset(self, now: float) -> None:
        self._state.task_key = ""
        self._state.started_at = now
        self._state.last_seen_at = now
        self._state.nudged_2h = False
        self._state.nudged_4h = False
