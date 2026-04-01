"""Commitment and deadline extractor — Proactive Intelligence Tier 3.

Extracts temporal commitments from user messages using a regex battery.
Extracted commitments are stored in memory with deadline metadata so
the TaskScheduler can fire reminders at the right time.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterator


# ── patterns ──────────────────────────────────────────────────────────────────

_DEADLINE_PATTERNS: list[tuple[re.Pattern, float]] = [
    # "by Friday", "before noon", "on Monday"
    (re.compile(
        r"\b(by|before|on|until)\s+"
        r"(monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
        r"tomorrow|today|noon|midnight|eod|eow|end of (day|week|month)|\d{1,2}(:\d{2})?\s*(am|pm)?)",
        re.IGNORECASE,
    ), 0.85),
    # "need to fix this by next week"
    (re.compile(
        r"\b(need to|must|should|have to|going to|will)\s+.{5,60}?\s+"
        r"(by|before|on|until)\s+\w+",
        re.IGNORECASE,
    ), 0.75),
    # "deadline Friday", "due tomorrow", "ship by Dec 10"
    (re.compile(
        r"\b(deadline|due|ship|deploy|release|submit|launch|push|merge|present)\b.{0,40}?"
        r"(by|on|before|until|at)?\s*"
        r"(monday|tuesday|wednesday|thursday|friday|saturday|sunday|tomorrow|today|\d{1,2}[/-]\d{1,2}|\d+ (days?|hours?|weeks?))",
        re.IGNORECASE,
    ), 0.80),
    # "I'll have it ready by noon"
    (re.compile(
        r"\b(i'?ll|i will|we'?ll|we will)\s+.{3,60}?\s+"
        r"(by|before|at|on)\s+\w+",
        re.IGNORECASE,
    ), 0.70),
    # "in 2 days", "within 3 hours"
    (re.compile(
        r"\b(in|within)\s+\d+\s+(hours?|days?|weeks?|minutes?)",
        re.IGNORECASE,
    ), 0.65),
]

_RELATIVE_DEADLINE_MAP = {
    "today": 0,
    "eod": 0,
    "tomorrow": 1,
    "monday": None,
    "tuesday": None,
    "wednesday": None,
    "thursday": None,
    "friday": None,
    "saturday": None,
    "sunday": None,
    "eow": None,
    "end of week": None,
    "next week": 7,
}

_DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def _estimate_deadline(match_text: str) -> datetime | None:
    """Best-effort deadline estimation from matched pattern text."""
    text = match_text.lower()
    now = datetime.now(timezone.utc)

    for day_name in _DAYS:
        if day_name in text:
            target_wd = _DAYS.index(day_name)
            current_wd = now.weekday()
            delta = (target_wd - current_wd) % 7 or 7
            return (now + timedelta(days=delta)).replace(
                hour=17, minute=0, second=0, microsecond=0
            )

    if "tomorrow" in text:
        return (now + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
    if "today" in text or "eod" in text:
        return now.replace(hour=18, minute=0, second=0, microsecond=0)
    if "next week" in text or "eow" in text:
        return (now + timedelta(days=7)).replace(hour=9, minute=0, second=0, microsecond=0)

    # "in N days/hours"
    m = re.search(r"in\s+(\d+)\s+(hours?|days?|weeks?)", text)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        if "hour" in unit:
            return now + timedelta(hours=n)
        if "day" in unit:
            return now + timedelta(days=n)
        if "week" in unit:
            return now + timedelta(weeks=n)

    return None


# ── data class ────────────────────────────────────────────────────────────────

@dataclass
class Commitment:
    description: str
    matched_text: str
    deadline: datetime | None
    confidence: float
    source_role: str = "user"
    extracted_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_memory_text(self) -> str:
        dl = self.deadline.strftime("%Y-%m-%d %H:%M UTC") if self.deadline else "unspecified"
        return f"[COMMITMENT] {self.description} — deadline: {dl}"

    def to_dict(self) -> dict:
        return {
            "description": self.description,
            "matched_text": self.matched_text,
            "deadline": self.deadline.isoformat() if self.deadline else None,
            "confidence": self.confidence,
            "source_role": self.source_role,
            "extracted_at": self.extracted_at.isoformat(),
        }


# ── public API ────────────────────────────────────────────────────────────────

_MAX_TEXT_LEN = 4000


def extract_commitments(
    text: str,
    role: str = "user",
    min_confidence: float = 0.6,
) -> list[Commitment]:
    """Extract temporal commitments from a single conversation turn.

    Only processes `role == "user"` messages — NOVA's own responses are ignored
    to prevent self-commitments from being tracked.
    """
    if role != "user":
        return []
    if not text or not text.strip():
        return []

    text = text[:_MAX_TEXT_LEN]
    results: list[Commitment] = []

    for pattern, base_confidence in _DEADLINE_PATTERNS:
        for m in pattern.finditer(text):
            matched = m.group(0)
            deadline = _estimate_deadline(matched)
            # Boost confidence if deadline was parseable
            confidence = base_confidence + (0.1 if deadline else 0.0)
            if confidence >= min_confidence:
                # Use a surrounding window as description
                start = max(0, m.start() - 20)
                end = min(len(text), m.end() + 40)
                description = text[start:end].strip()
                results.append(
                    Commitment(
                        description=description,
                        matched_text=matched,
                        deadline=deadline,
                        confidence=round(min(1.0, confidence), 3),
                        source_role=role,
                    )
                )

    # Deduplicate by matched_text
    seen: set[str] = set()
    unique: list[Commitment] = []
    for c in results:
        key = c.matched_text.lower().strip()
        if key not in seen:
            seen.add(key)
            unique.append(c)

    return unique[:20]  # cap per message


def iter_commitments_from_history(
    history: list[dict],
    min_confidence: float = 0.6,
) -> Iterator[Commitment]:
    """Yield commitments extracted from a full session history list."""
    for turn in history:
        role = turn.get("role", "")
        content = turn.get("content", "")
        if isinstance(content, str):
            yield from extract_commitments(content, role=role, min_confidence=min_confidence)
