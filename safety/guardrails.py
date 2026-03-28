"""Risk scoring, confirmation policy, and action logging guardrails.

Fixes applied:
- 1.9: Emergency stop flag is persisted to ~/.jarvis/emergency_stop so it survives restarts.
- 2.12: Guardrails log is now rotated via loguru (10 MB, 7-day retention).
- 1.1: Sensitive tool args (api_key, token, password, secret) are scrubbed before logging.
- Security 4.3: Path-based high-risk scoring for System32/etc writes.
- Security Critical: Registry write path allowlist enforced.
- _SYSTEM_PATHS moved to module level (not re-created on every check() call).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
import threading
import time
from typing import Any, Callable

from config.settings import settings

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DESTRUCTIVE_TOOLS = {
    "win32_api.delete",
    "win32_api.registry_write",
    "win32_api.kill_process",
    "adb.delete_file",
    "adb.send_sms",
    "browser.fill",
}

_MEDIUM_RISK_HINTS = {
    "write", "move", "rename", "launch", "open", "connect", "send", "post", "upload",
}

_HIGH_RISK_HINTS = {
    "delete", "drop", "rm", "kill", "shutdown", "format", "wipe", "registry",
}

# Arg keys whose values must be scrubbed from logs
_SENSITIVE_ARG_KEYS = {
    "api_key", "token", "password", "secret", "access_key",
    "private_key", "auth_token", "bearer_token", "api_secret",
}

# File/path tools that can target sensitive system directories
_FILE_MUTATING_TOOLS = {
    "win32_api.write", "win32_api.move", "win32_api.delete", "win32_api.launch_process",
}

# Critical system paths — writes here always score >= 9 regardless of keyword match
_SYSTEM_PATHS = (
    "system32", "syswow64", "program files", "windows\\system",
    "/etc/", "/usr/bin/", "/usr/lib/", "/bin/", "/sbin/",
)

# Registry paths allowed for write — everything else is blocked
_REGISTRY_WRITE_ALLOWLIST = (
    "hkey_current_user\\software\\nova",
    "hkey_current_user\\environment",
)

# Path for persistent emergency-stop flag — moved to ~/.jarvis/ to prevent
# unauthorised creation by other processes in the working directory
_EMERGENCY_STOP_FILE = Path.home() / ".jarvis" / "emergency_stop"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _scrub_args(args: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of args with sensitive values masked."""
    scrubbed: dict[str, Any] = {}
    for key, value in args.items():
        if key.lower() in _SENSITIVE_ARG_KEYS:
            scrubbed[key] = "***REDACTED***"
        elif isinstance(value, dict):
            scrubbed[key] = _scrub_args(value)
        else:
            scrubbed[key] = value
    return scrubbed


# ---------------------------------------------------------------------------
# Guardrails class
# ---------------------------------------------------------------------------

class Guardrails:
    def __init__(
        self,
        threshold_high: int = 7,
        medium_countdown_seconds: int = 5,
        log_path: str = "logs/guardrails_actions.jsonl",
    ):
        self.threshold_high = threshold_high
        self.medium_countdown_seconds = medium_countdown_seconds
        self._log_path = Path(log_path)
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

        # Load persisted emergency stop on startup
        self._emergency_stop = threading.Event()
        if _EMERGENCY_STOP_FILE.exists():
            self._emergency_stop.set()

        # Use loguru rotating sink (10 MB / 7 days)
        self._init_rotating_log()

    def _init_rotating_log(self) -> None:
        try:
            from loguru import logger as _lg
            _lg.add(
                str(self._log_path),
                rotation="10 MB",
                retention="7 days",
                compression="gz",
                format="{message}",
                filter=lambda record: record["extra"].get("guardrails") is True,
                level="DEBUG",
            )
            self._loguru_logger = _lg.bind(guardrails=True)
        except Exception:
            self._loguru_logger = None

    def _log_line(self, line: str) -> None:
        """Write a JSONL line — via loguru if available, else direct append."""
        if self._loguru_logger is not None:
            try:
                self._loguru_logger.debug(line)
                return
            except Exception:
                pass
        with self._lock:
            with self._log_path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")

    def _risk_level(self, score: int) -> str:
        if score >= self.threshold_high:
            return "high"
        if score >= 4:
            return "medium"
        return "low"

    def _build_plan(self, tool_call) -> str:
        return (
            f"Tool: {tool_call.tool}\n"
            f"Args: {json.dumps(_scrub_args(tool_call.args), ensure_ascii=False, sort_keys=True)}"
        )

    def check(self, tool_call) -> RiskResult:
        args_text = json.dumps(tool_call.args, ensure_ascii=False).lower()
        tool_name = tool_call.tool.lower()

        # Registry write: enforce path allowlist — block immediately if not allowed
        if tool_name == "win32_api.registry_write":
            path = str(tool_call.args.get("path", "")).lower()
            if not any(path.startswith(a) for a in _REGISTRY_WRITE_ALLOWLIST):
                return RiskResult(
                    score=10,
                    level="high",
                    blocked=True,
                    reason="registry_path_not_in_allowlist",
                    requires_confirmation=False,
                    plan=self._build_plan(tool_call),
                )

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

        # Path-based escalation: file-mutating tools targeting critical system directories
        # always score >= 9 regardless of keyword matches
        if tool_name in _FILE_MUTATING_TOOLS:
            for arg_val in tool_call.args.values():
                if isinstance(arg_val, str):
                    av_lower = arg_val.lower().replace("\\\\", "/").replace("\\", "/")
                    if any(sp in av_lower for sp in _SYSTEM_PATHS):
                        score = max(score, 9)
                        break

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
        """Activate emergency stop and persist to disk so it survives restarts."""
        self._emergency_stop.set()
        try:
            # Ensure parent directory exists before writing
            _EMERGENCY_STOP_FILE.parent.mkdir(parents=True, exist_ok=True)
            _EMERGENCY_STOP_FILE.write_text("1", encoding="utf-8")
        except Exception:
            pass

    def clear_emergency_stop(self) -> None:
        """Clear the emergency stop and remove the persistence file."""
        self._emergency_stop.clear()
        try:
            _EMERGENCY_STOP_FILE.unlink(missing_ok=True)
        except Exception:
            pass

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
        """Log the action — scrubbing sensitive args before writing."""
        entry = ActionLogEntry(
            timestamp=datetime.now(timezone.utc).isoformat(),
            tool=tool_call.tool,
            args=_scrub_args(tool_call.args),
            risk_score=risk.score,
            risk_level=risk.level,
            requires_confirmation=risk.requires_confirmation,
            confirmed_by=confirmed_by,
            status=status,
            result=result,
            reason=risk.reason,
        )
        self._log_line(json.dumps(asdict(entry), ensure_ascii=False))


guardrails = Guardrails(threshold_high=settings.RISK_CONFIRM_THRESHOLD)
