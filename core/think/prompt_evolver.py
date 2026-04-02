"""Feedback-Driven System Prompt Evolver — Proactive Intelligence Tier 5.

Runs A/B tests on system prompt variants derived from weekly insights.
Successful variants (>5% improvement in goal success rate) graduate
to become the new SOUL.md tail section.
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

from core.think.reasoning import _SOUL_FILE_LOCK

log = logging.getLogger(__name__)

_VARIANTS_PATH    = Path(".jarvis/prompt_variants.json")
_SOUL_PATH        = Path("SOUL.md")
_MIN_GOALS_TO_AB  = 10      # goals executed before running A/B
_AB_BUCKET_RATIO  = 5       # 1 in 5 sessions use the candidate variant
_MIN_GOALS_TO_EVAL = 20     # goals run in A/B before evaluating
_IMPROVE_THRESHOLD = 0.05   # +5% success rate to graduate
_REGRESS_THRESHOLD = 0.10   # -10% to immediately retire
_MAX_VARIANT_WORDS = 50     # keep prompt additions short


@dataclass
class PromptVariant:
    variant_id: str
    prompt_suffix: str
    goals_run: int = 0
    goals_succeeded: int = 0
    baseline_success_rate: float = 0.0
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    graduated: bool = False
    retired: bool = False

    @property
    def success_rate(self) -> float:
        return self.goals_succeeded / self.goals_run if self.goals_run else 0.0

    def to_dict(self) -> dict:
        return {
            "variant_id": self.variant_id,
            "prompt_suffix": self.prompt_suffix,
            "goals_run": self.goals_run,
            "goals_succeeded": self.goals_succeeded,
            "baseline_success_rate": self.baseline_success_rate,
            "created_at": self.created_at,
            "graduated": self.graduated,
            "retired": self.retired,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PromptVariant":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class PromptEvolver:
    """Manages one active A/B prompt variant at a time."""

    def __init__(
        self,
        llm_ask_fn: Callable[[str, str], str],
        notify_fn: Callable[[str], None],
        get_baseline_success_rate_fn: Callable[[], float],
        soul_path: Path = _SOUL_PATH,
        variants_path: Path = _VARIANTS_PATH,
    ):
        self._ask = llm_ask_fn
        self._notify = notify_fn
        self._get_baseline = get_baseline_success_rate_fn
        self._soul_path = soul_path
        self._variants_path = variants_path
        self._lock = threading.Lock()
        self._active_variant: PromptVariant | None = None
        self._total_goals_since_last_evolution = 0
        self._load()

    # ── persistence ───────────────────────────────────────────────────────────

    def _load(self) -> None:
        if not self._variants_path.exists():
            return
        try:
            data = json.loads(self._variants_path.read_text(encoding="utf-8"))
            active = data.get("active")
            if active:
                v = PromptVariant.from_dict(active)
                if not v.graduated and not v.retired:
                    self._active_variant = v
        except Exception:
            pass

    def _save(self) -> None:
        try:
            self._variants_path.parent.mkdir(parents=True, exist_ok=True)
            payload: dict[str, Any] = {}
            if self._active_variant:
                payload["active"] = self._active_variant.to_dict()
            self._variants_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception:
            pass

    # ── A/B bucket assignment (deterministic by session+date) ─────────────────

    def is_variant_session(self, session_id: str) -> bool:
        """Return True if this session should use the candidate prompt."""
        with self._lock:
            if not self._active_variant:
                return False
        digest = hashlib.md5(f"{session_id}{date.today().isoformat()}".encode()).hexdigest()
        return int(digest, 16) % _AB_BUCKET_RATIO == 0

    def get_active_suffix(self, session_id: str) -> str:
        """Return prompt suffix if this session is in the variant bucket."""
        if not self.is_variant_session(session_id):
            return ""
        with self._lock:
            return self._active_variant.prompt_suffix if self._active_variant else ""

    # ── recording ─────────────────────────────────────────────────────────────

    def record_goal_outcome(self, session_id: str, succeeded: bool) -> None:
        with self._lock:
            self._total_goals_since_last_evolution += 1
            if not self._active_variant:
                return
            if self.is_variant_session(session_id):
                self._active_variant.goals_run += 1
                if succeeded:
                    self._active_variant.goals_succeeded += 1
                self._save()

        # Check if we should evaluate
        with self._lock:
            variant = self._active_variant
        if variant and variant.goals_run >= _MIN_GOALS_TO_EVAL:
            self._evaluate_variant()

    # ── proposal ──────────────────────────────────────────────────────────────

    def propose_variant(self, weekly_insight: str, current_soul: str) -> None:
        """Called after weekly insight extraction if enough goals have run."""
        with self._lock:
            if self._active_variant:
                return  # one A/B test at a time
            if self._total_goals_since_last_evolution < _MIN_GOALS_TO_AB:
                return

        try:
            prompt = (
                f"Based on this user insight:\n{weekly_insight}\n\n"
                f"Suggest ONE short addition (max {_MAX_VARIANT_WORDS} words) to this system prompt "
                "that would make the assistant more proactively helpful. "
                "Return ONLY the addition text, no explanations:\n\n"
                f"{current_soul[-2000:]}"
            )
            suffix = self._ask(prompt, "You are a prompt engineering expert.").strip()

            # Trim to max words
            words = suffix.split()
            if len(words) > _MAX_VARIANT_WORDS:
                suffix = " ".join(words[:_MAX_VARIANT_WORDS])

            if not suffix:
                return

            baseline = self._get_baseline()
            variant = PromptVariant(
                variant_id=f"v_{date.today().isoformat()}",
                prompt_suffix=suffix,
                baseline_success_rate=baseline,
            )
            with self._lock:
                self._active_variant = variant
                self._total_goals_since_last_evolution = 0
                self._save()

            log.info("[prompt_evolver] new variant proposed: %s...", suffix[:60])
        except Exception as exc:
            log.warning("[prompt_evolver] proposal failed: %s", exc)

    # ── evaluation ────────────────────────────────────────────────────────────

    def _evaluate_variant(self) -> None:
        with self._lock:
            v = self._active_variant
            if not v:
                return

        improvement = v.success_rate - v.baseline_success_rate

        if improvement >= _IMPROVE_THRESHOLD:
            self._graduate_variant(v)
        elif improvement <= -_REGRESS_THRESHOLD:
            self._retire_variant(v, reason="regression")
        # else: keep running until more data

    def _graduate_variant(self, v: PromptVariant) -> None:
        """Append the suffix to SOUL.md and notify."""
        try:
            with _SOUL_FILE_LOCK:
                soul_content = self._soul_path.read_text(encoding="utf-8") if self._soul_path.exists() else ""
                if v.prompt_suffix not in soul_content:
                    with self._soul_path.open("a", encoding="utf-8") as f:
                        f.write(f"\n\n<!-- Auto-evolved {date.today().isoformat()} -->\n{v.prompt_suffix}\n")
            v.graduated = True
            with self._lock:
                self._active_variant = None
                self._save()
            msg = (
                f"✨ *Prompt evolved!*\nI updated my working style based on what's been working best "
                f"(+{(v.success_rate - v.baseline_success_rate)*100:.1f}% goal success rate). "
                "You can review the change in `SOUL.md`."
            )
            self._notify(msg)
            log.info("[prompt_evolver] variant graduated: %s", v.variant_id)
        except Exception as exc:
            log.warning("[prompt_evolver] graduation failed: %s", exc)

    def _retire_variant(self, v: PromptVariant, reason: str = "") -> None:
        v.retired = True
        with self._lock:
            self._active_variant = None
            self._save()
        log.info("[prompt_evolver] variant retired (%s): %s", reason, v.variant_id)
