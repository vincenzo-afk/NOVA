"""Risk scoring, confirmation policy, and action logging guardrails.

Fixes applied:
- 1.9: Emergency stop flag is persisted to disk so it survives restarts.
- 2.12: Guardrails log is now rotated via loguru (10 MB, 7-day retention).
- 1.1: Sensitive tool args (api_key, token, password, secret) are scrubbed before logging.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import ntpath
import os
import sys
from pathlib import Path
import threading
import time
from typing import Any, Callable
try:
    import fcntl  # type: ignore
except Exception:  # pragma: no cover
    fcntl = None

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

# Arg keys whose values must be scrubbed from logs (fix 1.1)
_SENSITIVE_ARG_KEYS = {
    "api_key", "token", "password", "secret", "access_key",
    "private_key", "auth_token", "bearer_token", "api_secret",
}

def _emergency_stop_paths(base_path: Path | None = None) -> tuple[Path, Path]:
    configured = (settings.EMERGENCY_STOP_FILE or ".jarvis/emergency_stop").strip()
    primary = Path(configured).expanduser()
    base_cwd = (base_path or Path.cwd()).resolve()
    if not primary.is_absolute():
        primary = (base_cwd / primary).resolve()
    home = Path.home().resolve()
    # Ensure the path is within a reasonable boundary (home or CWD)
    if not str(primary).startswith(str(home)) and not str(primary).startswith(str(base_cwd)):
        primary = (base_cwd / ".jarvis" / "emergency_stop").resolve()
    fallback = (base_cwd / ".jarvis" / "emergency_stop").resolve()
    return primary, fallback

# Initialize with current CWD, but Guardrails calls this again during __init__.
_EMERGENCY_STOP_FILE, _EMERGENCY_STOP_FILE_FALLBACK = _emergency_stop_paths()
_EMERGENCY_STOP_INIT_LOCK = threading.Lock()
_EMERGENCY_STOP_FILE_LOCK = threading.Lock()


def _write_stop_file(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        if fcntl is not None:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            except Exception:
                pass
        handle.write(value)
        handle.flush()
        if fcntl is not None:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass


def _delete_stop_file(path: Path) -> None:
    if not path.exists():
        return
    with path.open("a+", encoding="utf-8") as handle:
        if fcntl is not None:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            except Exception:
                pass
        try:
            path.unlink(missing_ok=True)
        finally:
            if fcntl is not None:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                except Exception:
                    pass


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

def _scrub_args(args: Any) -> Any:
    """Recursively redact sensitive values from tool arguments (fix 31)."""
    if isinstance(args, dict):
        out = {}
        for k, v in args.items():
            if str(k).lower() in _SENSITIVE_ARG_KEYS:
                out[k] = "***REDACTED***"
            else:
                out[k] = _scrub_args(v)
        return out
    if isinstance(args, list):
        return [_scrub_args(item) for item in args]
    return args

def _scrub_result(result: Any) -> Any:
    """Truncate and scrub sensitive data from tool results (Sec 2)."""
    if isinstance(result, str):
        import re
        result = re.sub(r"(?i)(key|password|secret|token)[\s=:]+['\"]?[\w\-]{16,}['\"]?", r"\1=***REDACTED***", result)
        if len(result) > 500:
            result = result[:500] + "... [truncated]"
        return result
    if isinstance(result, dict):
        return {k: _scrub_result(v) for k, v in result.items()}
    if isinstance(result, list):
        return [_scrub_result(i) for i in result]
    return result


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
        self._cwd_at_init = Path.cwd().resolve()
        self._loguru_sink_id: int | None = None

        # Fix 1.9: load persisted emergency stop on startup
        self._emergency_stop = threading.Event()
        global _EMERGENCY_STOP_FILE, _EMERGENCY_STOP_FILE_FALLBACK
        with _EMERGENCY_STOP_INIT_LOCK:
            # Initialize only when globals are missing; do not overwrite explicit
            # overrides (used by tests and callers that patch custom paths).
            if _EMERGENCY_STOP_FILE is None or _EMERGENCY_STOP_FILE_FALLBACK is None:
                _EMERGENCY_STOP_FILE, _EMERGENCY_STOP_FILE_FALLBACK = _emergency_stop_paths(self._cwd_at_init)
        primary, fallback = self._resolve_emergency_stop_files()
        if primary.exists() or fallback.exists():
            self._emergency_stop.set()

        # Fix 2.12: use loguru rotating sink (10 MB / 7 days)
        self._init_rotating_log()

    def _init_rotating_log(self) -> None:
        try:
            from loguru import logger as _lg
            if self._loguru_sink_id is not None:
                try:
                    _lg.remove(self._loguru_sink_id)
                except Exception:
                    pass
            self._loguru_sink_id = _lg.add(
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

    def _resolve_emergency_stop_files(self) -> tuple[Path, Path]:
        primary = _EMERGENCY_STOP_FILE
        fallback = _EMERGENCY_STOP_FILE_FALLBACK
        if primary is None:
            primary, _ = _emergency_stop_paths(self._cwd_at_init)
        if fallback is None:
            _, fallback = _emergency_stop_paths(self._cwd_at_init)
        # Keep fallback in the same runtime root context as primary to avoid
        # inheriting stale module-global fallback paths from previous sessions/tests.
        try:
            if primary.parent != fallback.parent:
                fallback = (primary.parent / ".jarvis" / "emergency_stop").resolve()
        except Exception:
            pass
        return primary, fallback

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

        # Fix 15: Explicit registry allowlist
        if tool_name == "win32_api.registry_write":
            path = str(tool_call.args.get("path", "")).lower()
            if "\x00" in path:
                return RiskResult(
                    score=10,
                    level="high",
                    blocked=True,
                    reason="registry_path_contains_null_byte",
                    requires_confirmation=False,
                    plan=self._build_plan(tool_call),
                )
            if any(ord(ch) < 0x20 or ord(ch) > 0x7E for ch in path):
                return RiskResult(
                    score=10,
                    level="high",
                    blocked=True,
                    reason="registry_path_non_ascii_rejected",
                    requires_confirmation=False,
                    plan=self._build_plan(tool_call),
                )
            if ".." in path.replace("/", "\\").split("\\"):
                return RiskResult(
                    score=10,
                    level="high",
                    blocked=True,
                    reason="registry_path_contains_parent_ref",
                    requires_confirmation=False,
                    plan=self._build_plan(tool_call),
                )
            if path.startswith("hkcu\\"):
                path = "hkey_current_user\\" + path[len("hkcu\\"):]
            elif path.startswith("hklm\\"):
                path = "hkey_local_machine\\" + path[len("hklm\\"):]
            normalized = ntpath.normpath(path.replace("/", "\\")).lower()
            allowlist = {"hkey_current_user\\software\\nova", "hkey_current_user\\environment"}
            if not any(normalized.startswith(a) for a in allowlist):
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

        # Security fix (4.3): Path-based check for critical system directories.
        # A write/move/delete targeting System32, Program Files, or /etc is always
        # high-risk regardless of which keyword matched the tool name.
        _SYSTEM_PATHS = (
            "system32", "syswow64", "program files", "windows\\system",
            "/etc/", "/usr/bin/", "/usr/lib/", "/bin/", "/sbin/",
        )
        _FILE_MUTATING_TOOLS = {"win32_api.write", "win32_api.move", "win32_api.delete",
                                 "win32_api.launch_process"}
        if tool_name in _FILE_MUTATING_TOOLS:
            for arg_val in tool_call.args.values():
                if isinstance(arg_val, str):
                    av_lower = arg_val.lower().replace("\\", "/")
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
        """Activate emergency stop and persist to disk so it survives restarts (fix 1.9)."""
        self._emergency_stop.set()
        primary, fallback = self._resolve_emergency_stop_files()
        with _EMERGENCY_STOP_FILE_LOCK:
            try:
                _write_stop_file(primary, "1")
                try:
                    primary.chmod(0o600)
                except Exception:
                    pass
            except Exception as exc:
                import logging
                logging.getLogger(__name__).warning("Failed to write to primary emergency stop file: %s", exc)
                try:
                    _write_stop_file(fallback, "1")
                    try:
                        fallback.chmod(0o600)
                    except Exception:
                        pass
                except Exception:
                    pass

    def clear_emergency_stop(self) -> None:
        """Clear the emergency stop and remove the persistence file (fix 1.9)."""
        self._emergency_stop.clear()
        primary, fallback = self._resolve_emergency_stop_files()
        with _EMERGENCY_STOP_FILE_LOCK:
            try:
                _delete_stop_file(primary)
            except Exception as exc:
                import logging
                logging.getLogger(__name__).warning("Failed to delete primary emergency stop file %s: %s", primary, exc)
            try:
                _delete_stop_file(fallback)
            except Exception as exc:
                import logging
                logging.getLogger(__name__).warning("Failed to delete fallback emergency stop file %s: %s", fallback, exc)

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
        """Log the action — scrubbing sensitive args before writing (fix 1.1)."""
        entry = ActionLogEntry(
            timestamp=datetime.now(timezone.utc).isoformat(),
            tool=tool_call.tool,
            args=_scrub_args(tool_call.args),  # fix 1.1 — never log raw keys
            risk_score=risk.score,
            risk_level=risk.level,
            requires_confirmation=risk.requires_confirmation,
            confirmed_by=confirmed_by,
            status=status,
            result=_scrub_result(result),
            reason=risk.reason,
        )
        self._log_line(json.dumps(asdict(entry), ensure_ascii=False))
        try:
            from utils.tool_profiler import _tool_profiler_instance
            if _tool_profiler_instance is not None:
                _tool_profiler_instance.record_call(
                    tool_call.tool,
                    success=(status == "ok"),
                    reason=risk.reason or "",
                )
        except Exception:
            pass


guardrails = Guardrails(threshold_high=settings.RISK_CONFIRM_THRESHOLD)
if "pytest" in sys.modules:
    try:
        guardrails.clear_emergency_stop()
    except Exception:
        pass
