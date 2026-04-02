"""Cross-Session Insight Extractor — Proactive Intelligence Tier 2.

Runs a weekly cross-session analysis on Sunday night and surfaces the
results on Monday morning (first activity trigger).
"""
from __future__ import annotations

import logging
import threading
from datetime import date, datetime, timezone
from typing import Any, Callable

log = logging.getLogger(__name__)

_INSIGHT_MAX_TOKENS = 8000
_INSIGHT_MEMORY_SOURCE = "weekly_insight"


class InsightExtractor:
    """Weekly cross-session theme extractor.

    Wired up in NOVAApp._start_health_monitoring() as a TaskScheduler job.
    """

    def __init__(
        self,
        llm_ask_fn: Callable[[str, str], str],
        memory_get_all_fn: Callable[[str], list[dict]],
        memory_add_fn: Callable[[str, str, dict], None],
        notify_fn: Callable[[str], None],
        estimate_tokens_fn: Callable[[str], int],
        session_list_fn: Callable[[], list[str]],
    ):
        self._ask = llm_ask_fn
        self._get_all = memory_get_all_fn
        self._add = memory_add_fn
        self._notify = notify_fn
        self._estimate_tokens = estimate_tokens_fn
        self._list_sessions = session_list_fn
        self._last_insight_week: int | None = None
        self._pending_insight: str | None = None
        self._lock = threading.Lock()

    # ── weekly job (runs Sunday ~2:30am via scheduler) ─────────────────────────

    def run_weekly_extraction(self) -> str | None:
        """Called by TaskScheduler on Sunday at 2:30am."""
        now = datetime.now(timezone.utc)
        week_num = now.isocalendar()[1]

        with self._lock:
            if self._last_insight_week == week_num:
                return None  # already ran this week
            self._last_insight_week = week_num

        try:
            sessions = self._list_sessions()
            if not sessions:
                return None

            all_texts: list[str] = []
            for sid in sessions[:10]:  # cap sessions
                try:
                    memories = self._get_all(sid)
                    for m in (memories or []):
                        text = m.get("memory") or m.get("text") or ""
                        if text:
                            all_texts.append(text)
                except Exception:
                    continue

            if not all_texts:
                return None

            # Token-cap the corpus
            combined = "\n".join(all_texts)
            while self._estimate_tokens(combined) > _INSIGHT_MAX_TOKENS and all_texts:
                all_texts = all_texts[: len(all_texts) // 2]
                combined = "\n".join(all_texts)

            prompt = (
                "Identify 5 recurring themes, unresolved problems, or emerging patterns "
                "across these work sessions. Be specific and actionable. "
                "Return each insight as a plain bullet point.\n\n"
                f"{combined}"
            )

            insight = self._ask(
                prompt,
                "You are a thoughtful analyst reviewing a developer's work history.",
            ).strip()

            if not insight:
                return None

            today_str = date.today().isoformat()
            self._add(
                f"[WEEKLY INSIGHT — {today_str}]\n{insight}",
                sessions[0],
                {"source": _INSIGHT_MEMORY_SOURCE, "date": today_str},
            )

            with self._lock:
                self._pending_insight = insight

            log.info("[insight_extractor] weekly insight stored for week %d", week_num)
            return insight

        except Exception as exc:
            log.warning("[insight_extractor] extraction failed: %s", exc)
            return None

    # ── Monday morning surface (called on first activity) ──────────────────────

    def maybe_surface_monday_insight(self) -> None:
        """Surface the pending insight on Monday morning (first call)."""
        now = datetime.now(timezone.utc)
        if now.weekday() != 0:  # 0 = Monday
            return

        with self._lock:
            insight = self._pending_insight
            if not insight:
                return
            self._pending_insight = None

        try:
            message = (
                "📊 *Weekly Insight* — based on last week's sessions:\n\n"
                f"{insight}\n\n"
                "_Want me to schedule a focused work block on any of these?_"
            )
            self._notify(message)
        except Exception as exc:
            log.warning("[insight_extractor] surface failed: %s", exc)
