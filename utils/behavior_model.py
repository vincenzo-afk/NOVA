"""Behavioral Rhythm Modeler — Proactive Intelligence Tier 2.

Maintains a persistent model of the user's temporal work patterns, enabling
activity prediction and proactive context pre-loading.

Data is stored locally in .jarvis/behavior_model.json — never sent externally.
"""
from __future__ import annotations

import json
import threading
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


_MODEL_PATH = Path(".jarvis/behavior_model.json")
_MAX_DAYS = 30  # rolling window


class BehaviorModel:
    """Records and predicts user activity patterns based on temporal signals."""

    def __init__(self, persist_path: Path = _MODEL_PATH, privacy_mode: bool = False):
        self._path = persist_path
        self.privacy_mode = privacy_mode
        self._lock = threading.Lock()
        # structure: {weekday_str: {hour_str: {app: count, topic: count, sessions: int}}}
        self._data: dict[str, dict[str, dict[str, Any]]] = defaultdict(
            lambda: defaultdict(lambda: defaultdict(int))
        )
        self._load()

    # ── persistence ───────────────────────────────────────────────────────────

    def _load(self) -> None:
        if self._path.exists():
            try:
                raw = json.loads(self._path.read_text(encoding="utf-8"))
                for wd, hours in raw.items():
                    for hr, counts in hours.items():
                        for k, v in counts.items():
                            self._data[wd][hr][k] = v
            except Exception:
                pass

    def _snapshot_locked(self) -> dict[str, dict[str, dict[str, Any]]]:
        payload: dict[str, dict[str, dict[str, Any]]] = {}
        for wd, hours in self._data.items():
            payload[wd] = {}
            for hr, counts in hours.items():
                payload[wd][hr] = dict(counts)
        return payload

    def _save(self, snapshot: dict[str, dict[str, dict[str, Any]]] | None = None) -> None:
        if self.privacy_mode:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            payload = snapshot if snapshot is not None else {}
            self._path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception:
            pass

    # ── recording ─────────────────────────────────────────────────────────────

    def record_activity(
        self,
        provider: str,
        session_id: str,
        hour: int | None = None,
        weekday: int | None = None,
    ) -> None:
        if self.privacy_mode:
            return
        now = datetime.now()
        wd = str(weekday if weekday is not None else now.weekday())
        hr = str(hour if hour is not None else now.hour)
        with self._lock:
            self._data[wd][hr]["llm_calls"] = self._data[wd][hr].get("llm_calls", 0) + 1
            self._data[wd][hr][f"provider_{provider}"] = (
                self._data[wd][hr].get(f"provider_{provider}", 0) + 1
            )
            self._data[wd][hr][f"session_{session_id[:16]}"] = (
                self._data[wd][hr].get(f"session_{session_id[:16]}", 0) + 1
            )
            snapshot = self._snapshot_locked()
        self._save(snapshot)

    def record_screen_state(
        self,
        active_app: str,
        scene_type: str,
        hour: int | None = None,
        weekday: int | None = None,
    ) -> None:
        if self.privacy_mode:
            return
        now = datetime.now()
        wd = str(weekday if weekday is not None else now.weekday())
        hr = str(hour if hour is not None else now.hour)
        with self._lock:
            if active_app:
                key = f"app_{active_app[:32]}"
                self._data[wd][hr][key] = self._data[wd][hr].get(key, 0) + 1
            if scene_type:
                key = f"scene_{scene_type[:32]}"
                self._data[wd][hr][key] = self._data[wd][hr].get(key, 0) + 1
            snapshot = self._snapshot_locked()
        self._save(snapshot)

    # ── prediction ────────────────────────────────────────────────────────────

    def predict_next_activity(
        self,
        current_hour: int | None = None,
        weekday: int | None = None,
        top_k: int = 5,
    ) -> list[tuple[str, float]]:
        """Return (activity, confidence) pairs sorted by frequency for this time slot."""
        now = datetime.now()
        wd = str(weekday if weekday is not None else now.weekday())
        hr = str(current_hour if current_hour is not None else now.hour)
        with self._lock:
            counts = dict(self._data.get(wd, {}).get(hr, {}))
        if not counts:
            return []
        total = max(1, sum(counts.values()))
        ranked = sorted(counts.items(), key=lambda x: x[1], reverse=True)[:top_k]
        return [(k, round(v / total, 3)) for k, v in ranked]

    def get_profile_summary(self) -> dict[str, Any]:
        """Return a human-readable profile for the `behavior.profile` tool."""
        now = datetime.now()
        predictions = self.predict_next_activity()
        return {
            "current_weekday": now.strftime("%A"),
            "current_hour": now.hour,
            "predicted_activities": [
                {"activity": act, "confidence": conf} for act, conf in predictions
            ],
            "privacy_mode": self.privacy_mode,
            "data_days_tracked": len(self._data),
        }
