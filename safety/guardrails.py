"""Risk scoring, confirmation policy, and action logging guardrails."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
import threading
import time
from typing import Any, Callable

from config.settings import settings


DESTRUCTIVE_TOOLS = {
    "win32_api.delete",
    "win32_api.registry_write",
    "win32_api.kill_process",
    "adb.delete_file",
    "adb.send_sms",
    "browser.fill",
}

_MEDIUM_RISK_HINTS = {
    "write",
    "move",
    "rename",
    "launch",
    "open",
    "connect",
    "send",
    "post",
    "upload",
}

_HIGH_RISK_HINTS = {
    "delete",
    "drop",
    "rm",
    "kill",
    "shutdown",
    "format",
    "wipe",
    "registry",
}


@dataclass
class RiskResult:
    score: int
    level: str
    blocked: bool = False
    reason: str = ""
    requires_confirmation: bool = False
    auto_confirm_seconds: int | None = None
    plan: str = ""


@dataclass
class ActionLogEntry:
    timestamp: str
    tool: str
    args: dict[str, Any]
    risk_score: int
    risk_level: str
    requires_confirmation: bool
    confirmed_by: str
    status: str
    result: Any = field(default_factory=dict)
    reason: str = ""


class Guardrails:
    def __init__(
        self,
        threshold_high: int = 7,
        medium_countdown_seconds: int = 5,
        log_path: str = "logs/guardrails_actions.jsonl",
    ):
        self.threshold_high = threshold_high
        self.medium_countdown_seconds = medium_countdown_seconds
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._emergency_stop = threading.Event()

    def _risk_level(self, score: int) -> str:
        if score >= self.threshold_high:
            return "high"
        if score >= 4:
            return "medium"
        return "low"

    def _build_plan(self, tool_call) -> str:
        return (
            f"Tool: {tool_call.tool}\n"
            f"Args: {json.dumps(tool_call.args, ensure_ascii=False, sort_keys=True)}"
        )

    def check(self, tool_call) -> RiskResult:
        args_text = json.dumps(tool_call.args, ensure_ascii=False).lower()
        tool_name = tool_call.tool.lower()

        score = 2
        if any(token in tool_name for token in ("win32_api.", "adb.", "browser.")):
            score += 1
        if any(h in tool_name for h in _MEDIUM_RISK_HINTS):
            score += 1
        if any(h in args_text for h in _MEDIUM_RISK_HINTS):
            score += 1
        if any(h in tool_name for h in _HIGH_RISK_HINTS):
            score += 3
        if any(h in args_text for h in _HIGH_RISK_HINTS):
            score += 3

        if tool_call.tool in DESTRUCTIVE_TOOLS:
            score = max(score, 9)

        score = max(0, min(10, score))
        level = self._risk_level(score)

        return RiskResult(
            score=score,
            level=level,
            requires_confirmation=(level == "high"),
            auto_confirm_seconds=self.medium_countdown_seconds if level == "medium" else None,
            plan=self._build_plan(tool_call),
        )

    def emergency_stop(self) -> None:
        self._emergency_stop.set()

    def clear_emergency_stop(self) -> None:
        self._emergency_stop.clear()

    def is_emergency_stopped(self) -> bool:
        return self._emergency_stop.is_set()

    def authorize(
        self,
        tool_call,
        risk: RiskResult,
        confirm_callback: Callable[[str], bool] | None = None,
        announce_callback: Callable[[str], None] | None = None,
        input_fn: Callable[[str], str] = input,
        sleep_fn: Callable[[float], None] = time.sleep,
        dry_run: bool = False,
    ) -> RiskResult:
        if self.is_emergency_stopped():
            risk.blocked = True
            risk.reason = "emergency_stop_active"
            return risk

        if dry_run:
            risk.reason = "dry_run"
            return risk

        if risk.level == "low":
            return risk

        if risk.level == "medium":
            message = (
                "Medium-risk action. Plan:\n"
                f"{risk.plan}\n"
                f"Auto-confirming in {risk.auto_confirm_seconds}s..."
            )
            if announce_callback:
                announce_callback(message)
            else:
                print(message)
            sleep_fn(float(risk.auto_confirm_seconds or self.medium_countdown_seconds))
            return risk

        prompt = (
            "High-risk action requires explicit confirmation.\n"
            f"{risk.plan}\n"
            "Type 'y' to continue: "
        )
        approved = (
            confirm_callback(prompt)
            if confirm_callback is not None
            else input_fn(prompt).strip().lower() in {"y", "yes", "confirm"}
        )
        if not approved:
            risk.blocked = True
            risk.reason = "user_declined"
        return risk

    def log(
        self,
        tool_call,
        risk: RiskResult,
        result: Any,
        *,
        status: str = "ok",
        confirmed_by: str = "system",
    ) -> None:
        entry = ActionLogEntry(
            timestamp=datetime.now(timezone.utc).isoformat(),
            tool=tool_call.tool,
            args=tool_call.args,
            risk_score=risk.score,
            risk_level=risk.level,
            requires_confirmation=risk.requires_confirmation,
            confirmed_by=confirmed_by,
            status=status,
            result=result,
            reason=risk.reason,
        )

        line = json.dumps(asdict(entry), ensure_ascii=False)
        with self._lock:
            with self.log_path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")


guardrails = Guardrails(threshold_high=settings.RISK_CONFIRM_THRESHOLD)
