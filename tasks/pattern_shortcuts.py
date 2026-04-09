"""Weekly pattern shortcut compiler.

Compiles repeated tool-call sequences from guardrails action logs into
named shortcuts that can be replayed.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import tempfile
from typing import Any

from core.tools.dispatcher import ToolCall


class PatternShortcutCompiler:
    def __init__(
        self,
        *,
        log_path: str = "logs/guardrails_actions.jsonl",
        output_path: str = ".jarvis/pattern_shortcuts.json",
    ) -> None:
        self.log_path = Path(log_path)
        self.output_path = Path(output_path)

    def compile(
        self,
        *,
        lookback_days: int = 7,
        min_repeats: int = 3,
        max_sequence_len: int = 3,
        top_k: int = 10,
    ) -> dict[str, Any]:
        events = self._read_events(lookback_days=lookback_days)
        if len(events) < 2:
            payload = {"generated_at": _utc_now_iso(), "shortcuts": []}
            self._write_payload(payload)
            return payload

        seq_counter: Counter[str] = Counter()
        seq_values: dict[str, list[dict[str, Any]]] = {}
        n_max = max(2, int(max_sequence_len))
        for n in range(2, n_max + 1):
            for i in range(0, len(events) - n + 1):
                window = events[i : i + n]
                steps = [
                    {
                        "tool": e["tool"],
                        "args": self._generalize_args(e.get("args", {})),
                    }
                    for e in window
                ]
                key = json.dumps(steps, sort_keys=True, ensure_ascii=False)
                seq_counter[key] += 1
                seq_values[key] = steps

        compiled: list[dict[str, Any]] = []
        used_names: set[str] = set()
        for key, count in seq_counter.most_common():
            if count < max(2, int(min_repeats)):
                continue
            steps = seq_values.get(key, [])
            if not steps:
                continue
            name = self._build_name(steps, used_names)
            used_names.add(name)
            compiled.append(
                {
                    "name": name,
                    "invocations": int(count),
                    "steps": steps,
                    "description": self._describe(steps),
                }
            )
            if len(compiled) >= max(1, int(top_k)):
                break

        payload = {"generated_at": _utc_now_iso(), "shortcuts": compiled}
        self._write_payload(payload)
        return payload

    def list_shortcuts(self) -> list[dict[str, Any]]:
        payload = self._read_payload()
        return list(payload.get("shortcuts", []))

    def run_shortcut(self, *, name: str, dispatcher, dry_run: bool = False) -> dict[str, Any]:
        payload = self._read_payload()
        shortcuts = payload.get("shortcuts", [])
        target = None
        for item in shortcuts:
            if str(item.get("name", "")).lower() == name.strip().lower():
                target = item
                break
        if target is None:
            return {"status": "error", "reason": "shortcut_not_found", "name": name}

        steps = target.get("steps", [])
        results: list[dict[str, Any]] = []
        for idx, step in enumerate(steps):
            raw_args = dict(step.get("args", {}) or {})
            if self._contains_placeholder(raw_args):
                return {
                    "status": "error",
                    "reason": "shortcut_contains_generalized_placeholders",
                    "name": target.get("name"),
                    "step_index": idx,
                }
            call = ToolCall(tool=str(step.get("tool", "")), args=raw_args)
            result = dispatcher.execute(tool_call=call, dry_run=bool(dry_run))
            results.append({"step_index": idx, "tool": call.tool, "result": result})
            if result.get("status") in {"blocked", "cancelled", "error", "rate_limited"} or result.get("error"):
                return {
                    "status": "partial",
                    "name": target.get("name"),
                    "completed_steps": idx,
                    "results": results,
                }
        return {"status": "ok", "name": target.get("name"), "results": results}

    def _read_events(self, *, lookback_days: int) -> list[dict[str, Any]]:
        if not self.log_path.exists():
            return []
        cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, int(lookback_days)))
        events: list[dict[str, Any]] = []
        try:
            with self.log_path.open("r", encoding="utf-8") as handle:
                for raw in handle:
                    line = raw.strip()
                    if not line:
                        continue
                    try:
                        item = json.loads(line)
                    except Exception:
                        continue
                    tool = str(item.get("tool", "")).strip()
                    if not tool:
                        continue
                    if str(item.get("status", "")).strip().lower() not in {"ok", "allowed"}:
                        continue
                    ts = _parse_ts(item.get("timestamp"))
                    if ts is not None and ts < cutoff:
                        continue
                    events.append(
                        {
                            "tool": tool,
                            "args": item.get("args", {}) or {},
                            "timestamp": item.get("timestamp"),
                        }
                    )
        except Exception:
            return []
        return events

    def _read_payload(self) -> dict[str, Any]:
        try:
            if not self.output_path.exists():
                return {"generated_at": None, "shortcuts": []}
            return json.loads(self.output_path.read_text(encoding="utf-8"))
        except Exception:
            return {"generated_at": None, "shortcuts": []}

    def _write_payload(self, payload: dict[str, Any]) -> None:
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(self.output_path.parent),
            delete=False,
            suffix=".tmp",
        ) as tmp:
            tmp.write(json.dumps(payload, indent=2, ensure_ascii=False))
            tmp_path = Path(tmp.name)
        tmp_path.replace(self.output_path)

    def _build_name(self, steps: list[dict[str, Any]], used_names: set[str]) -> str:
        parts: list[str] = []
        for step in steps[:2]:
            tool = str(step.get("tool", "")).lower()
            tail = tool.split(".")[-1] if "." in tool else tool
            tail = re.sub(r"[^a-z0-9_]+", "_", tail).strip("_")
            if tail:
                parts.append(tail)
        base = "sc_" + "_".join(parts or ["workflow"])
        name = base
        i = 2
        while name in used_names:
            name = f"{base}_{i}"
            i += 1
        return name

    @staticmethod
    def _describe(steps: list[dict[str, Any]]) -> str:
        tools = [str(s.get("tool", "")).strip() for s in steps if str(s.get("tool", "")).strip()]
        return " -> ".join(tools[:6])

    def _generalize_args(self, args: Any) -> Any:
        if isinstance(args, dict):
            # Preserve shape, not values, so repeated logical workflows can match.
            return {k: self._generalize_args(v) for k, v in sorted(args.items())}
        if isinstance(args, list):
            return [self._generalize_args(v) for v in args[:5]]
        return "<value>"

    def _contains_placeholder(self, value: Any) -> bool:
        if isinstance(value, dict):
            return any(self._contains_placeholder(v) for v in value.values())
        if isinstance(value, list):
            return any(self._contains_placeholder(v) for v in value)
        return value == "<value>"


def _parse_ts(value: Any) -> datetime | None:
    try:
        raw = str(value).strip()
        if not raw:
            return None
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
