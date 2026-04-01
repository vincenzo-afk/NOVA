"""Goal Template Library — Proactive Intelligence Tier 5.

Learns goal step sequences from successful executions and reuses them
for future similar goals, skipping the LLM planning call entirely.
"""
from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


_LIBRARY_PATH = Path(".jarvis/goal_templates.json")
_MIN_SUCCESS_COUNT = 2     # need 2 successes before template is trusted
_MATCH_THRESHOLD   = 0.60  # keyword Jaccard similarity to use a template
_MAX_TEMPLATES     = 200

# Regex patterns for value generalisation
_URL_RE       = re.compile(r"https?://[^\s\"']+")
_PATH_RE      = re.compile(r"(/[\w./-]+|~?/[\w./-]+)")
_DATE_RE      = re.compile(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}(/\d{2,4})?\b")
_NUMBER_RE    = re.compile(r"\b\d+\b")


def _generalise_value(v: Any) -> Any:
    """Replace concrete values in args with typed placeholders."""
    if isinstance(v, str):
        v = _URL_RE.sub("{url}", v)
        v = _PATH_RE.sub("{filepath}", v)
        v = _DATE_RE.sub("{date}", v)
        v = _NUMBER_RE.sub("{n}", v)
        return v
    return v


def _generalise_steps(steps: list[dict]) -> list[dict]:
    generalised = []
    for step in steps:
        g = {"tool": step.get("tool", "")}
        raw_args = step.get("args") or {}
        g["args"] = {k: _generalise_value(v) for k, v in raw_args.items()}
        generalised.append(g)
    return generalised


def _keywords(text: str) -> set[str]:
    return {w.lower() for w in re.findall(r"[a-z]{4,}", text.lower())}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# ── data class ────────────────────────────────────────────────────────────────

@dataclass
class GoalTemplate:
    name: str
    trigger_keywords: list[str]
    steps: list[dict]
    success_count: int = 0
    avg_completion_time: float = 0.0
    required_tools: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "trigger_keywords": self.trigger_keywords,
            "steps": self.steps,
            "success_count": self.success_count,
            "avg_completion_time": self.avg_completion_time,
            "required_tools": self.required_tools,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "GoalTemplate":
        return cls(
            name=d.get("name", ""),
            trigger_keywords=d.get("trigger_keywords", []),
            steps=d.get("steps", []),
            success_count=int(d.get("success_count", 0)),
            avg_completion_time=float(d.get("avg_completion_time", 0.0)),
            required_tools=d.get("required_tools", []),
        )


# ── library ───────────────────────────────────────────────────────────────────

class GoalTemplateLibrary:
    """Persistent, learning goal template store."""

    def __init__(self, path: Path = _LIBRARY_PATH):
        self._path = path
        self._lock = threading.Lock()
        self._templates: list[GoalTemplate] = []
        self._load()

    # ── persistence ───────────────────────────────────────────────────────────

    def _load(self) -> None:
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                self._templates = [GoalTemplate.from_dict(d) for d in data]
            except Exception:
                self._templates = []

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            payload = [t.to_dict() for t in self._templates[:_MAX_TEMPLATES]]
            self._path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception:
            pass

    # ── learning ──────────────────────────────────────────────────────────────

    def record_success(
        self,
        goal_description: str,
        steps: list[dict],
        completion_time: float = 0.0,
        available_tools: set[str] | None = None,
    ) -> None:
        """Record a successful goal execution and upsert a template."""
        if not steps or len(steps) < 2:
            return  # only learn multi-step goals

        kws = list(_keywords(goal_description))
        generalised = _generalise_steps(steps)
        required = list({s.get("tool", "") for s in steps if s.get("tool")})

        # Infer template name from top keywords
        name_parts = [k for k in kws[:4] if len(k) > 4]
        name = " ".join(name_parts) or goal_description[:40]

        with self._lock:
            # Find existing template with high overlap
            for t in self._templates:
                if _jaccard(set(t.trigger_keywords), set(kws)) >= 0.70:
                    t.success_count += 1
                    t.avg_completion_time = (
                        (t.avg_completion_time * (t.success_count - 1) + completion_time)
                        / t.success_count
                    )
                    # Refresh steps with latest successful sequence
                    t.steps = generalised
                    t.required_tools = required
                    self._save()
                    return

            # New template
            self._templates.append(
                GoalTemplate(
                    name=name,
                    trigger_keywords=kws[:20],
                    steps=generalised,
                    success_count=1,
                    avg_completion_time=completion_time,
                    required_tools=required,
                )
            )
            # Prune oldest if over cap
            if len(self._templates) > _MAX_TEMPLATES:
                self._templates.sort(key=lambda x: x.success_count, reverse=True)
                self._templates = self._templates[:_MAX_TEMPLATES]
            self._save()

    # ── matching ──────────────────────────────────────────────────────────────

    def find_matching_template(
        self,
        goal: str,
        available_tools: set[str] | None = None,
    ) -> GoalTemplate | None:
        """Return the best-matching trusted template, or None."""
        kws = _keywords(goal)
        best: GoalTemplate | None = None
        best_score = 0.0

        with self._lock:
            candidates = list(self._templates)

        for t in candidates:
            if t.success_count < _MIN_SUCCESS_COUNT:
                continue
            # Validate required tools are still available
            if available_tools is not None:
                if not all(tool in available_tools for tool in t.required_tools):
                    continue
            score = _jaccard(kws, set(t.trigger_keywords))
            if score > best_score:
                best_score = score
                best = t

        if best and best_score >= _MATCH_THRESHOLD:
            return best
        return None

    def invalidate_stale(self, available_tools: set[str]) -> int:
        """Remove templates whose required tools no longer exist. Returns count removed."""
        with self._lock:
            before = len(self._templates)
            self._templates = [
                t for t in self._templates
                if all(tool in available_tools for tool in t.required_tools)
            ]
            removed = before - len(self._templates)
            if removed:
                self._save()
        return removed

    def all_templates(self) -> list[dict]:
        with self._lock:
            return [t.to_dict() for t in self._templates]
