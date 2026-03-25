"""Tracks token usage by session/provider."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date


@dataclass
class UsageEntry:
    input_tokens: int = 0
    output_tokens: int = 0


class UsageTracker:
    def __init__(self):
        self._daily: dict[date, dict[str, UsageEntry]] = defaultdict(lambda: defaultdict(UsageEntry))

    def add(self, provider: str, input_tokens: int, output_tokens: int) -> None:
        entry = self._daily[date.today()][provider]
        entry.input_tokens += input_tokens
        entry.output_tokens += output_tokens

    def today_summary(self) -> dict[str, dict[str, int]]:
        day = self._daily.get(date.today(), {})
        return {
            provider: {
                "input_tokens": data.input_tokens,
                "output_tokens": data.output_tokens,
                "total_tokens": data.input_tokens + data.output_tokens,
            }
            for provider, data in day.items()
        }
