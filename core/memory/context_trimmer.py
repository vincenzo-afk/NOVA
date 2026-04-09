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
    _summary_inflight: set[str] = field(default_factory=set)
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
            last_count = self._last_summarized_count.get(session_id, 0)
            if len(older) == last_count and summary:
                return summary, recent

            snippet = " ".join(
                f"{turn.get('role', 'user')}: {turn.get('content', '').strip()}"
                for turn in older
                if turn.get("content")
            )
            if session_id in self._summary_inflight:
                return summary, recent
            self._summary_inflight.add(session_id)

        try:
            compressed = summarizer(snippet) if summarizer else snippet[:700]
            if not str(compressed).strip():
                with self._lock:
                    self._summary_inflight.discard(session_id)
                return "", recent

            with self._lock:
                latest = self.summaries.get(session_id, "")
                if latest:
                    latest = (latest + " " + compressed).strip()[:1200]
                else:
                    latest = compressed[:1200]
                self.summaries[session_id] = latest
                self._last_summarized_count[session_id] = len(older)
                self._summary_inflight.discard(session_id)
                return latest, recent
        except Exception:
            with self._lock:
                self._summary_inflight.discard(session_id)
            return summary, recent
