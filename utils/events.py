"""Shared formatting helpers for recent event history."""

from __future__ import annotations

from datetime import datetime
from typing import Any


def format_event_log(events: list[dict[str, Any]]) -> str:
    if not events:
        return "No recent alerts."

    lines = []
    for event in events[:20]:
        kind = str(event.get("kind", "event")).title()
        message = str(event.get("message", "")).strip()
        raw_timestamp = event.get("timestamp")
        try:
            timestamp = datetime.fromtimestamp(float(raw_timestamp)).strftime("%H:%M:%S")
        except Exception:
            timestamp = str(raw_timestamp).strip()
        lines.append(f"[{kind}] {message} ({timestamp})")
    return "\n".join(lines)
