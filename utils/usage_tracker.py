"""Tracks token usage by session/provider."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
import json
from pathlib import Path
import threading


@dataclass
class UsageEntry:
    input_tokens: int = 0
    output_tokens: int = 0


class UsageTracker:
    def __init__(self, persist_path: str | None = None):
        self._daily: dict[date, dict[str, dict[str, UsageEntry]]] = defaultdict(
            lambda: defaultdict(lambda: defaultdict(UsageEntry))
        )
        self._max_days = 8
        self._persist_path = Path(persist_path) if persist_path else None
        self._lock = threading.RLock()
        self._persist_timer: threading.Timer | None = None
        self._persist_interval_seconds = 2.0
        self._dirty = False
        self._load()

    def _load(self) -> None:
        try:
            if self._persist_path is None:
                return
            if not self._persist_path.exists():
                return
            data = json.loads(self._persist_path.read_text(encoding="utf-8"))
            for day_key, sessions in (data or {}).items():
                d = date.fromisoformat(day_key)
                for session_id, providers in (sessions or {}).items():
                    for provider, entry in (providers or {}).items():
                        self._daily[d][session_id][provider] = UsageEntry(
                            input_tokens=int(entry.get("input_tokens", 0)),
                            output_tokens=int(entry.get("output_tokens", 0)),
                        )
        except Exception:
            pass

    def _persist(self) -> None:
        try:
            if self._persist_path is None:
                return
            if not self._dirty:
                return
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            payload: dict[str, dict[str, dict[str, dict[str, int]]]] = {}
            for day_key, sessions in self._daily.items():
                payload[day_key.isoformat()] = {}
                for session_id, providers in sessions.items():
                    payload[day_key.isoformat()][session_id] = {}
                    for provider, entry in providers.items():
                        payload[day_key.isoformat()][session_id][provider] = {
                            "input_tokens": entry.input_tokens,
                            "output_tokens": entry.output_tokens,
                        }
            self._persist_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            self._dirty = False
        except Exception:
            pass

    def _schedule_persist(self) -> None:
        if self._persist_path is None:
            return
        if self._persist_timer and self._persist_timer.is_alive():
            return

        def _flush() -> None:
            with self._lock:
                self._persist_timer = None
                self._persist()

        timer = threading.Timer(self._persist_interval_seconds, _flush)
        timer.daemon = True
        self._persist_timer = timer
        timer.start()

    def add(
        self,
        provider: str,
        input_tokens: int,
        output_tokens: int,
        session_id: str = "default",
        when: date | None = None,
    ) -> None:
        with self._lock:
            today = when or date.today()
            cutoff = today - timedelta(days=self._max_days - 1)
            for day_key in list(self._daily.keys()):
                if day_key < cutoff:
                    self._daily.pop(day_key, None)
            entry = self._daily[today][session_id][provider]
            entry.input_tokens += input_tokens
            entry.output_tokens += output_tokens
            self._dirty = True
            self._schedule_persist()

    def flush(self) -> None:
        with self._lock:
            timer = self._persist_timer
            self._persist_timer = None
            if timer and timer.is_alive():
                timer.cancel()
            self._persist()

    def today_summary(self, session_id: str | None = None) -> dict[str, dict[str, int]]:
        return self._summary_for_dates([date.today()], session_id=session_id)

    def weekly_summary(
        self,
        session_id: str | None = None,
        end_date: date | None = None,
        days: int = 7,
    ) -> dict[str, dict[str, int]]:
        end = end_date or date.today()
        span = max(1, int(days))
        dates = [end - timedelta(days=offset) for offset in range(span)]
        return self._summary_for_dates(dates, session_id=session_id)

    def _summary_for_dates(self, dates: list[date], session_id: str | None = None) -> dict[str, dict[str, int]]:
        totals: dict[str, UsageEntry] = defaultdict(UsageEntry)
        with self._lock:
            for day_key in dates:
                day = self._daily.get(day_key, {})
                providers = day.get(session_id, {}) if session_id is not None else _merge_sessions(day)
                for provider, data in providers.items():
                    entry = totals[provider]
                    entry.input_tokens += data.input_tokens
                    entry.output_tokens += data.output_tokens
        return {
            provider: {
                "input_tokens": data.input_tokens,
                "output_tokens": data.output_tokens,
                "total_tokens": data.input_tokens + data.output_tokens,
            }
            for provider, data in totals.items()
        }

    def total_tokens_today(self, session_id: str | None = None) -> int:
        summary = self.today_summary(session_id=session_id)
        return sum(item["total_tokens"] for item in summary.values())

    def total_tokens_week(self, session_id: str | None = None, end_date: date | None = None) -> int:
        summary = self.weekly_summary(session_id=session_id, end_date=end_date)
        return sum(item["total_tokens"] for item in summary.values())


def _merge_sessions(day: dict[str, dict[str, UsageEntry]]) -> dict[str, UsageEntry]:
    merged: dict[str, UsageEntry] = defaultdict(UsageEntry)
    for providers in day.values():
        for provider, data in providers.items():
            entry = merged[provider]
            entry.input_tokens += data.input_tokens
            entry.output_tokens += data.output_tokens
    return merged
