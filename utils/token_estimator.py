"""Lightweight token estimation helpers."""

from __future__ import annotations

from typing import Iterable


def estimate_tokens(text: str) -> int:
    """Rough token estimate: ~3.5 characters per token."""
    if not text:
        return 0
    return max(1, int(len(text) / 3.5))


def estimate_tokens_from_messages(messages: Iterable[dict]) -> int:
    total = 0
    for msg in messages:
        total += estimate_tokens(str(msg.get("content", "")))
    return total
