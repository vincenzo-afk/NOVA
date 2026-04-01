"""Emotion state engine with proactive trajectory prediction (Tier 2)."""

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

    def predict_from_context(
        self,
        hour: int,
        weekday: int,
        recent_errors: int = 0,
        session_length_minutes: float = 0.0,
    ) -> str:
        """Predict the appropriate emotion state from behavioral context signals.

        Decision tree (Tier 2 spec):
        - Late night + long session → empathetic
        - Many recent errors → urgent
        - Monday/Tuesday morning focus window → focused
        - Late-day wind-down → neutral
        - Meeting hours (midday) → cautious
        """
        # Late night after a very long session
        if hour >= 22 and session_length_minutes >= 180:
            return "empathetic"

        # Many errors detected in the last period
        if recent_errors >= 3:
            return "urgent"

        # End-of-day + long session → empathetic (wind-down check-in)
        if hour >= 17 and session_length_minutes >= 300:
            return "empathetic"

        # Monday/Tuesday morning prime focus window
        if weekday in {0, 1} and 9 <= hour <= 11:
            return "focused"

        # Any weekday morning focus window
        if weekday in {0, 1, 2, 3, 4} and 8 <= hour <= 10:
            return "focused"

        # Midday — potential meeting zone → cautious
        if 12 <= hour <= 14:
            return "cautious"

        return "neutral"

    def proactive_update(
        self,
        hour: int,
        weekday: int,
        recent_errors: int = 0,
        session_length_minutes: float = 0.0,
    ) -> str | None:
        """Apply trajectory prediction only if current state is neutral.

        Returns the new state if changed, else None.
        """
        if self.state != "neutral":
            return None
        predicted = self.predict_from_context(
            hour=hour,
            weekday=weekday,
            recent_errors=recent_errors,
            session_length_minutes=session_length_minutes,
        )
        if predicted != "neutral":
            self.state = predicted
            return predicted
        return None
