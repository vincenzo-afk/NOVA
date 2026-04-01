"""Tool Performance Profiler — Proactive Intelligence Tier 5.

Reads guardrails action logs and builds per-tool reliability statistics.
These stats are injected into the LLM planner prompt so the model learns
to prefer reliable tools and avoid flaky ones.
"""
from __future__ import annotations

import json
import threading
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


_LOG_PATH = Path("logs/guardrails_actions.jsonl")
_SEQUENCE_THRESHOLD = 8   # occurrences before a sequence is considered combinable
_RELOAD_EVERY_N = 50      # tool calls before re-scanning the log


class ToolStats:
    __slots__ = ("success", "failure", "total_latency_ms", "failure_reasons")

    def __init__(self) -> None:
        self.success: int = 0
        self.failure: int = 0
        self.total_latency_ms: float = 0.0
        self.failure_reasons: Counter = Counter()

    @property
    def total(self) -> int:
        return self.success + self.failure

    @property
    def success_rate(self) -> float:
        return self.success / self.total if self.total else 1.0

    @property
    def avg_latency_ms(self) -> float:
        return self.total_latency_ms / self.total if self.total else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "failure": self.failure,
            "success_rate_pct": round(self.success_rate * 100, 1),
            "avg_latency_ms": round(self.avg_latency_ms, 1),
            "top_failure_reasons": dict(self.failure_reasons.most_common(3)),
        }


class ToolProfiler:
    """Reads from guardrails JSONL log and surfaces reliability statistics."""

    def __init__(self, log_path: Path = _LOG_PATH):
        self._log_path = log_path
        self._lock = threading.Lock()
        self._stats: dict[str, ToolStats] = defaultdict(ToolStats)
        # Sequence tracking for combinable pattern detection
        self.call_sequence_counter: Counter = Counter()
        self._recent_calls: list[str] = []
        self._call_count = 0
        self._sequence_window = 3
        self._load_from_log()

    # ── log parsing ───────────────────────────────────────────────────────────

    def _load_from_log(self) -> None:
        if not self._log_path.exists():
            return
        try:
            lines = self._log_path.read_text(encoding="utf-8").splitlines()
        except Exception:
            return
        with self._lock:
            self._stats.clear()
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except Exception:
                    continue
                tool = entry.get("tool", "")
                if not tool:
                    continue
                status = entry.get("status", "")
                latency = float(entry.get("latency_ms", 0) or 0)
                if status == "allowed":
                    self._stats[tool].success += 1
                else:
                    self._stats[tool].failure += 1
                    reason = entry.get("reason", "unknown")
                    self._stats[tool].failure_reasons[reason] += 1
                self._stats[tool].total_latency_ms += latency

    def record_call(self, tool: str, success: bool, latency_ms: float = 0.0, reason: str = "") -> None:
        """Record a live tool call result (called from guardrails.log hook)."""
        with self._lock:
            if success:
                self._stats[tool].success += 1
            else:
                self._stats[tool].failure += 1
                if reason:
                    self._stats[tool].failure_reasons[reason] += 1
            self._stats[tool].total_latency_ms += latency_ms

            # Track sequences for combinable pattern detection
            self._recent_calls.append(tool)
            if len(self._recent_calls) > 20:
                self._recent_calls.pop(0)

            # Count 3-step windows
            calls = self._recent_calls
            if len(calls) >= self._sequence_window:
                seq = tuple(calls[-self._sequence_window:])
                self.call_sequence_counter[seq] += 1

            self._call_count += 1
            if self._call_count % _RELOAD_EVERY_N == 0:
                self._load_from_log()

    # ── queries ───────────────────────────────────────────────────────────────

    def get_reliability_ranking(self) -> list[tuple[str, float]]:
        """Return tools sorted by success rate (best first)."""
        with self._lock:
            return sorted(
                [(tool, stats.success_rate) for tool, stats in self._stats.items()],
                key=lambda x: x[1],
                reverse=True,
            )

    def get_least_reliable(self, n: int = 3) -> list[tuple[str, ToolStats]]:
        """Return the n least-reliable tools with sufficient call history."""
        with self._lock:
            eligible = [
                (tool, stats) for tool, stats in self._stats.items() if stats.total >= 5
            ]
            return sorted(eligible, key=lambda x: x[1].success_rate)[:n]

    def get_reliability_hints(self) -> dict[str, str]:
        """Return {tool_name: hint_str} for injection into tool schema prompts."""
        hints: dict[str, str] = {}
        with self._lock:
            for tool, stats in self._stats.items():
                if stats.total >= 3:
                    hints[tool] = (
                        f"reliability: {stats.success_rate * 100:.0f}%, "
                        f"avg {stats.avg_latency_ms:.0f}ms"
                    )
        return hints

    def get_planner_warning(self) -> str:
        """Return a warning string for the goal planner about flaky tools."""
        least = self.get_least_reliable(3)
        if not least:
            return ""
        names = [t for t, _ in least]
        return (
            f"These tools have had recent failures: {', '.join(names)}. "
            "Prefer alternatives when possible."
        )

    def detect_combinable_sequences(self) -> list[tuple[tuple[str, ...], int]]:
        """Return tool sequences called >= threshold times (candidates for plugin synthesis)."""
        with self._lock:
            return [
                (seq, count)
                for seq, count in self.call_sequence_counter.items()
                if count >= _SEQUENCE_THRESHOLD
            ]

    def all_stats(self) -> dict[str, Any]:
        """Return full stats dict for the `tool.stats` registered tool."""
        with self._lock:
            return {
                tool: stats.to_dict() for tool, stats in self._stats.items()
            }
