"""Environment snapshot for world-state prompt injection."""

from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import platform
import socket
import subprocess
import threading


def _run(cmd: list[str], timeout: float = 1.0) -> str:
    try:
        return subprocess.check_output(cmd, text=True, timeout=timeout).strip()
    except Exception:
        return ""


def _get_clipboard() -> str:
    system = platform.system().lower()
    if "darwin" in system:
        return _run(["pbpaste"])
    if "linux" in system:
        return _run(["xclip", "-o", "-selection", "clipboard"])
    if "windows" in system:
        return _run(["powershell", "Get-Clipboard"])
    return ""


def _foreground_app_and_title() -> tuple[str, str]:
    system = platform.system().lower()

    if "darwin" in system:
        app = _run(
            [
                "osascript",
                "-e",
                'tell application "System Events" to get name of first process whose frontmost is true',
            ]
        )
        title = _run(
            [
                "osascript",
                "-e",
                'tell application "System Events" to tell (first process whose frontmost is true) to '
                "get name of front window",
            ]
        )
        return app or "unknown", title or "unknown"

    if "linux" in system:
        active = _run(["xprop", "-root", "_NET_ACTIVE_WINDOW"])
        parts = active.split()
        window_id = parts[-1] if parts else ""
        if not window_id:
            return "unknown", "unknown"
        title = _run(["xprop", "-id", window_id, "WM_NAME"])
        app = _run(["xprop", "-id", window_id, "WM_CLASS"])
        return app or "unknown", title or "unknown"

    if "windows" in system:
        app = _run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "(Get-Process | Where-Object {$_.MainWindowHandle -ne 0} | "
                "Sort-Object StartTime -Descending | Select-Object -First 1).ProcessName",
            ],
            timeout=2.0,
        )
        title = _run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "(Get-Process | Where-Object {$_.MainWindowHandle -ne 0} | "
                "Sort-Object StartTime -Descending | Select-Object -First 1).MainWindowTitle",
            ],
            timeout=2.0,
        )
        return app or "unknown", title or "unknown"

    return "unknown", "unknown"


def _battery_pct() -> float | None:
    try:
        import psutil

        battery = psutil.sensors_battery()
        if battery is None:
            return None
        return float(battery.percent)
    except Exception:
        return None


def _last_active_file(clipboard: str) -> str | None:
    text = clipboard.strip()
    if not text:
        return None
    candidate = Path(text)
    if candidate.exists() and candidate.is_file():
        return str(candidate)
    return None


def _network_status() -> str:
    try:
        sock = socket.create_connection(("1.1.1.1", 53), timeout=1)
        sock.close()
        return "online"
    except OSError:
        return "offline"


import time

_ENVIRONMENT_CACHE: dict = {}
_ENVIRONMENT_CACHE_TTL = 10.0
_ENVIRONMENT_CACHE_TIME = 0.0
_ENVIRONMENT_LOCK = threading.RLock()

def snapshot_environment(include_clipboard: bool = True) -> dict:
    global _ENVIRONMENT_CACHE, _ENVIRONMENT_CACHE_TIME
    now = time.monotonic()
    with _ENVIRONMENT_LOCK:
        if now - _ENVIRONMENT_CACHE_TIME < _ENVIRONMENT_CACHE_TTL:
            # Return copied cache but update to current time dynamically
            cached = dict(_ENVIRONMENT_CACHE)
            cached["time"] = datetime.now().isoformat(timespec="seconds")
            if not include_clipboard:
                cached.pop("clipboard", None)
                cached["last_active_file"] = None
            return cached

        clipboard = _get_clipboard()[:1000] if include_clipboard else ""
        app, title = _foreground_app_and_title()
        result = {
            "time": datetime.now().isoformat(timespec="seconds"),
            "cwd": os.getcwd(),
            "os": platform.platform(),
            "hostname": socket.gethostname(),
            "network": _network_status(),
            "clipboard": clipboard,
            "foreground_app": app,
            "window_title": title,
            "battery_pct": _battery_pct(),
            "last_active_file": _last_active_file(clipboard) if include_clipboard else None,
        }
        _ENVIRONMENT_CACHE = dict(result)
        _ENVIRONMENT_CACHE_TIME = now
        return result
