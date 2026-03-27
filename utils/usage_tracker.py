"""Tracks token usage by session/provider."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta


@dataclass
class UsageEntry:
    input_tokens: int = 0
    output_tokens: int = 0


class UsageTracker:
    def __init__(self):
        self._daily: dict[date, dict[str, dict[str, UsageEntry]]] = defaultdict(
            lambda: defaultdict(lambda: defaultdict(UsageEntry))
        )

    def add(
        self,
        provider: str,
        input_tokens: int,
        output_tokens: int,
        session_id: str = "default",
        when: date | None = None,
    ) -> None:
        entry = self._daily[when or date.today()][session_id][provider]
        entry.input_tokens += input_tokens
        entry.output_tokens += output_tokens

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
