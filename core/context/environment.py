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


# ── Tier 1: Clipboard Content-Type Classifier (zero LLM cost) ─────────────────

def _classify_clipboard(text: str) -> str:
    """Classify clipboard content into one of four semantic types.

    Returns: 'CODE_BLOCK' | 'ERROR_TRACE' | 'URL' | 'PLAIN_TEXT'
    """
    if not text or not text.strip():
        return "PLAIN_TEXT"
    t = text[:4000]  # cap before pattern matching
    # Error trace
    if any(kw in t for kw in ("Traceback", "Error:", "Exception:", "EXCEPTION", "stack trace")):
        return "ERROR_TRACE"
    # Code block
    if any(kw in t for kw in ("def ", "class ", "import ", "function ", "return ", "const ", "let ", "var ")):
        return "CODE_BLOCK"
    if any(ch in t for ch in ("{}", "():", "() {", ";\n", "\t")):
        return "CODE_BLOCK"
    # URL
    if t.strip().startswith(("http://", "https://")) or "http://" in t or "https://" in t:
        return "URL"
    return "PLAIN_TEXT"


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

_ENVIRONMENT_CACHE_TTL = 10.0
_ENVIRONMENT_CACHE: dict[bool, dict] = {True: {}, False: {}}
_ENVIRONMENT_CACHE_TIME: dict[bool, float] = {True: 0.0, False: 0.0}
_ENVIRONMENT_LOCK = threading.RLock()
_REFRESH_INFLIGHT: dict[bool, bool] = {True: False, False: False}


def _compute_snapshot(include_clipboard: bool) -> dict:
    clipboard = _get_clipboard()[:1000] if include_clipboard else ""
    clipboard_type = _classify_clipboard(clipboard) if include_clipboard else "PLAIN_TEXT"
    app, title = _foreground_app_and_title()
    return {
        "time": datetime.now().isoformat(timespec="seconds"),
        "cwd": os.getcwd(),
        "os": platform.platform(),
        "hostname": socket.gethostname(),
        "network": _network_status(),
        "clipboard": clipboard,
        "clipboard_type": clipboard_type,
        "foreground_app": app,
        "window_title": title,
        "battery_pct": _battery_pct(),
        "last_active_file": _last_active_file(clipboard) if include_clipboard else None,
    }


def _refresh_background(include_clipboard: bool) -> None:
    global _ENVIRONMENT_CACHE, _ENVIRONMENT_CACHE_TIME, _REFRESH_INFLIGHT
    try:
        snapshot = _compute_snapshot(include_clipboard=include_clipboard)
        with _ENVIRONMENT_LOCK:
            _ENVIRONMENT_CACHE[include_clipboard] = dict(snapshot)
            _ENVIRONMENT_CACHE_TIME[include_clipboard] = time.monotonic()
    finally:
        with _ENVIRONMENT_LOCK:
            _REFRESH_INFLIGHT[include_clipboard] = False

def snapshot_environment(include_clipboard: bool = True) -> dict:
    global _ENVIRONMENT_CACHE, _ENVIRONMENT_CACHE_TIME, _REFRESH_INFLIGHT
    now = time.monotonic()
    with _ENVIRONMENT_LOCK:
        cache_time = _ENVIRONMENT_CACHE_TIME.get(include_clipboard, 0.0)
        cache = dict(_ENVIRONMENT_CACHE.get(include_clipboard, {}))
        if now - cache_time < _ENVIRONMENT_CACHE_TTL and cache:
            # Return copied cache but update to current time dynamically
            cached = dict(cache)
            cached["time"] = datetime.now().isoformat(timespec="seconds")
            if not include_clipboard:
                cached.pop("clipboard", None)
                cached["last_active_file"] = None
            return cached

        # If we already have data, return stale data immediately and refresh asynchronously.
        if cache:
            cached = dict(cache)
            cached["time"] = datetime.now().isoformat(timespec="seconds")
            if not include_clipboard:
                cached.pop("clipboard", None)
                cached["last_active_file"] = None
            if not _REFRESH_INFLIGHT.get(include_clipboard, False):
                _REFRESH_INFLIGHT[include_clipboard] = True
                threading.Thread(
                    target=_refresh_background,
                    args=(include_clipboard,),
                    daemon=True,
                ).start()
            return cached

    # First call has no cache yet; return quickly with a lightweight snapshot and refresh async.
    fallback = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "cwd": os.getcwd(),
        "os": platform.platform(),
        "hostname": socket.gethostname(),
        "network": "unknown",
        "foreground_app": "unknown",
        "window_title": "unknown",
        "battery_pct": _battery_pct(),
        "last_active_file": None,
    }
    if include_clipboard:
        fallback["clipboard"] = ""
    with _ENVIRONMENT_LOCK:
        if not _REFRESH_INFLIGHT.get(include_clipboard, False):
            _REFRESH_INFLIGHT[include_clipboard] = True
            threading.Thread(
                target=_refresh_background,
                args=(include_clipboard,),
                daemon=True,
            ).start()
    return fallback
