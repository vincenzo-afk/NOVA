"""History trimmer with rolling summary compression."""

from __future__ import annotations

from dataclasses import dataclass, field
import threading
from typing import Callable


@dataclass
class ContextTrimmer:
    max_raw_turns: int = 10
    summaries: dict[str, str] = field(default_factory=dict)
    _last_summarized_count: dict[str, int] = field(default_factory=dict)
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def trim(
        self,
        history: list[dict],
        session_id: str = "default",
        summarizer: Callable[[str], str] | None = None,
    ) -> tuple[str, list[dict]]:
        with self._lock:
            summary = self.summaries.get(session_id, "")
            if len(history) <= self.max_raw_turns:
                return summary, history

            older = history[: -self.max_raw_turns]
            recent = history[-self.max_raw_turns :]

            # Fix 3.3: Only recompute summary when the number of older turns changes
            last_count = self._last_summarized_count.get(session_id, 0)
            if len(older) == last_count and summary:
                # No new turns to summarize, reuse existing summary
                return summary, recent

            snippet = " ".join(
                f"{turn.get('role', 'user')}: {turn.get('content', '').strip()}"
                for turn in older
                if turn.get("content")
            )
            compressed = summarizer(snippet) if summarizer else snippet[:700]

            if summary:
                summary = (summary + " " + compressed).strip()[:1200]
            else:
                summary = compressed[:1200]

            self.summaries[session_id] = summary
            self._last_summarized_count[session_id] = len(older)
            return summary, recent
