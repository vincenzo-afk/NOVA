"""History trimmer with rolling summary compression."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass
class ContextTrimmer:
    max_raw_turns: int = 10
    summaries: dict[str, str] = field(default_factory=dict)

    def trim(
        self,
        history: list[dict],
        session_id: str = "default",
        summarizer: Callable[[str], str] | None = None,
    ) -> tuple[str, list[dict]]:
        summary = self.summaries.get(session_id, "")
        if len(history) <= self.max_raw_turns:
            return summary, history

        older = history[: -self.max_raw_turns]
        recent = history[-self.max_raw_turns :]

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
        return summary, recent
