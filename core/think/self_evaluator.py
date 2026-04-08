"""Silent post-response quality evaluator (Phase 16)."""

from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


_RATINGS_PATH = Path(".jarvis/response_ratings.jsonl")


@dataclass
class Rating:
    relevance: int
    actionability: int
    conciseness: int
    note: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "relevance": int(self.relevance),
            "actionability": int(self.actionability),
            "conciseness": int(self.conciseness),
            "note": str(self.note or "").strip(),
        }


class SelfEvaluator:
    def __init__(self, llm_ask_fn: Callable[[str, str], str], persist_path: Path = _RATINGS_PATH):
        self._llm_ask = llm_ask_fn
        self._path = persist_path
        self._lock = threading.Lock()

    def should_rate(
        self,
        *,
        assistant_text: str,
        estimated_tokens: int,
        daily_total_tokens: int,
        daily_alert_threshold: int,
        enabled: bool,
        min_response_tokens: int,
        skip_usage_pct: int,
    ) -> bool:
        if not enabled:
            return False
        if estimated_tokens < max(1, int(min_response_tokens)):
            return False
        if daily_alert_threshold > 0:
            pct = int((daily_total_tokens * 100) / max(1, daily_alert_threshold))
            if pct >= max(0, min(100, int(skip_usage_pct))):
                return False
        return bool(str(assistant_text).strip())

    def evaluate(self, *, prompt: str, response: str, session_id: str) -> dict[str, Any]:
        system = (
            "You are a strict evaluator. Rate the assistant response quality.\n"
            "Return JSON only with keys: relevance, actionability, conciseness, note.\n"
            "Scores must be integers 0-10."
        )
        user = (
            "Prompt:\n"
            f"{prompt}\n\n"
            "Response:\n"
            f"{response}\n\n"
            "Output JSON only."
        )
        raw = self._llm_ask(user, system)
        rating = self._parse(raw)
        payload = {
            "ts": int(time.time()),
            "session_id": str(session_id),
            "prompt_hash": hashlib.sha256(str(prompt).encode("utf-8")).hexdigest(),
            "ratings": rating.as_dict(),
        }
        self._append(payload)
        return payload

    def weekly_averages(self, *, session_prefix: str | None = None) -> dict[str, float]:
        rows = self._read_all()
        if session_prefix:
            rows = [r for r in rows if str(r.get("session_id", "")).startswith(session_prefix)]
        if not rows:
            return {"relevance": 0.0, "actionability": 0.0, "conciseness": 0.0}
        rel = [int((r.get("ratings") or {}).get("relevance", 0)) for r in rows]
        act = [int((r.get("ratings") or {}).get("actionability", 0)) for r in rows]
        con = [int((r.get("ratings") or {}).get("conciseness", 0)) for r in rows]
        return {
            "relevance": round(sum(rel) / max(1, len(rel)), 2),
            "actionability": round(sum(act) / max(1, len(act)), 2),
            "conciseness": round(sum(con) / max(1, len(con)), 2),
        }

    def _parse(self, text: str) -> Rating:
        raw = str(text or "").strip()
        data: dict[str, Any] = {}
        try:
            data = json.loads(raw)
        except Exception:
            start = raw.find("{")
            end = raw.rfind("}")
            if start >= 0 and end > start:
                try:
                    data = json.loads(raw[start : end + 1])
                except Exception:
                    data = {}
        return Rating(
            relevance=self._clamp_score(data.get("relevance", 7)),
            actionability=self._clamp_score(data.get("actionability", 7)),
            conciseness=self._clamp_score(data.get("conciseness", 7)),
            note=str(data.get("note", "")).strip()[:240],
        )

    @staticmethod
    def _clamp_score(value: Any) -> int:
        try:
            v = int(value)
        except Exception:
            v = 7
        return max(0, min(10, v))

    def _append(self, payload: dict[str, Any]) -> None:
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def _read_all(self) -> list[dict[str, Any]]:
        if not self._path.exists():
            return []
        rows: list[dict[str, Any]] = []
        with self._lock:
            for line in self._path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                except Exception:
                    continue
                if isinstance(item, dict):
                    rows.append(item)
        return rows
