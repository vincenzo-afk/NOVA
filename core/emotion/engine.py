"""Simple emotion state engine."""

from __future__ import annotations


class EmotionEngine:
    STATES = {
        "neutral",
        "focused",
        "concerned",
        "enthusiastic",
        "cautious",
        "empathetic",
        "urgent",
    }

    def __init__(self):
        self.state = "neutral"

    def update_from_signal(self, signal: str) -> str:
        normalized = signal.strip().lower()
        if normalized in self.STATES:
            self.state = normalized
            return self.state

        if any(word in normalized for word in ("error", "crash", "failed", "urgent")):
            self.state = "urgent"
        elif any(word in normalized for word in ("worried", "stressed", "sad", "tired")):
            self.state = "empathetic"
        elif any(word in normalized for word in ("careful", "danger", "risk")):
            self.state = "cautious"
        elif any(word in normalized for word in ("great", "done", "success", "awesome")):
            self.state = "enthusiastic"
        elif any(word in normalized for word in ("focus", "deadline", "work")):
            self.state = "focused"
        elif any(word in normalized for word in ("concern", "warning", "issue")):
            self.state = "concerned"
        else:
            self.state = "neutral"
        return self.state
