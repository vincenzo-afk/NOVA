"""Cross-platform window manager abstraction — Feature 14.

Routes window operations to the correct backend:
  - Windows  → win32gui (pywin32)
  - macOS    → osascript (AppleScript)
  - Linux    → xdotool (X11) or wmctrl (X11/Wayland)
  - Fallback → no-op with logged warning

All public methods return a uniform dict so callers don't need to know
which backend is active.
"""
from __future__ import annotations

import logging
import platform
import shutil
import subprocess
from typing import Any

log = logging.getLogger(__name__)


# ── helpers ──────────────────────────────────────────────────────────────────

def _run(cmd: list[str], timeout: float = 5.0) -> tuple[str, str, int]:
    """Run a command, return (stdout, stderr, returncode)."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip(), r.stderr.strip(), r.returncode
    except Exception as exc:
        return "", str(exc), -1


# ── backends ─────────────────────────────────────────────────────────────────

class _Win32Backend:
    """Windows window management via pywin32."""

    def list_windows(self) -> list[dict[str, Any]]:
        try:
            import win32gui  # type: ignore[import]

            results: list[dict[str, Any]] = []

            def _cb(hwnd, _):
                if win32gui.IsWindowVisible(hwnd):
                    title = win32gui.GetWindowText(hwnd)
                    if title:
                        results.append({"hwnd": hwnd, "title": title})

            win32gui.EnumWindows(_cb, None)
            return results
        except Exception as exc:
            log.warning("[win32] list_windows failed: %s", exc)
            return []

    def focus(self, title: str) -> dict[str, Any]:
        try:
            import win32gui, win32con  # type: ignore[import]

            hwnd = win32gui.FindWindow(None, title)
            if not hwnd:
                # Partial match
                for w in self.list_windows():
                    if title.lower() in w["title"].lower():
                        hwnd = w["hwnd"]
                        break
            if hwnd:
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                win32gui.SetForegroundWindow(hwnd)
                return {"focused": True, "title": win32gui.GetWindowText(hwnd)}
            return {"focused": False, "reason": "window_not_found"}
        except Exception as exc:
            return {"focused": False, "reason": str(exc)}

    def resize(self, title: str, width: int, height: int) -> dict[str, Any]:
        try:
            import win32gui  # type: ignore[import]

            hwnd = win32gui.FindWindow(None, title)
            if hwnd:
                rect = win32gui.GetWindowRect(hwnd)
                win32gui.MoveWindow(hwnd, rect[0], rect[1], width, height, True)
                return {"resized": True, "width": width, "height": height}
            return {"resized": False, "reason": "window_not_found"}
        except Exception as exc:
            return {"resized": False, "reason": str(exc)}

    def close(self, title: str) -> dict[str, Any]:
        try:
            import win32gui, win32con  # type: ignore[import]

            hwnd = win32gui.FindWindow(None, title)
            if hwnd:
                win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
                return {"closed": True}
            return {"closed": False, "reason": "window_not_found"}
        except Exception as exc:
            return {"closed": False, "reason": str(exc)}


class _MacOSBackend:
    """macOS window management via osascript."""

    def _script(self, code: str) -> tuple[str, str, int]:
        return _run(["osascript", "-e", code])

    def list_windows(self) -> list[dict[str, Any]]:
        script = (
            'tell application "System Events" to get name of every process '
            "whose background only is false"
        )
        out, _, rc = self._script(script)
        if rc != 0:
            return []
        names = [n.strip() for n in out.split(",") if n.strip()]
        return [{"title": n} for n in names]

    def focus(self, title: str) -> dict[str, Any]:
        script = f'tell application "{title}" to activate'
        _, err, rc = self._script(script)
        if rc == 0:
            return {"focused": True, "title": title}
        return {"focused": False, "reason": err or "osascript_failed"}

    def resize(self, title: str, width: int, height: int) -> dict[str, Any]:
        script = (
            f'tell application "{title}" to set bounds of front window '
            f"to {{0, 0, {width}, {height}}}"
        )
        _, err, rc = self._script(script)
        if rc == 0:
            return {"resized": True, "width": width, "height": height}
        return {"resized": False, "reason": err or "osascript_failed"}

    def close(self, title: str) -> dict[str, Any]:
        script = (
            f'tell application "System Events" to set procs to processes '
            f'whose name is "{title}"\n'
            f'if length of procs > 0 then tell front window of first item of procs to close'
        )
        _, err, rc = self._script(script)
        if rc == 0:
            return {"closed": True}
        return {"closed": False, "reason": err or "osascript_failed"}


class _XdotoolBackend:
    """Linux X11 window management via xdotool."""

    def list_windows(self) -> list[dict[str, Any]]:
        out, _, rc = _run(["xdotool", "search", "--name", ""])
        if rc != 0:
            return []
        ids = [i.strip() for i in out.splitlines() if i.strip()]
        results: list[dict[str, Any]] = []
        for wid in ids[:50]:
            name_out, _, _ = _run(["xdotool", "getwindowname", wid])
            if name_out:
                results.append({"id": wid, "title": name_out})
        return results

    def focus(self, title: str) -> dict[str, Any]:
        out, _, rc = _run(["xdotool", "search", "--name", title, "windowfocus", "--sync"])
        if rc == 0:
            return {"focused": True, "title": title}
        return {"focused": False, "reason": "xdotool_failed"}

    def resize(self, title: str, width: int, height: int) -> dict[str, Any]:
        out, _, _ = _run(["xdotool", "search", "--name", title])
        if not out:
            return {"resized": False, "reason": "window_not_found"}
        wid = out.splitlines()[0].strip()
        _, err, rc = _run(["xdotool", "windowsize", wid, str(width), str(height)])
        if rc == 0:
            return {"resized": True, "width": width, "height": height}
        return {"resized": False, "reason": err}

    def close(self, title: str) -> dict[str, Any]:
        out, _, _ = _run(["xdotool", "search", "--name", title])
        if not out:
            return {"closed": False, "reason": "window_not_found"}
        wid = out.splitlines()[0].strip()
        _, err, rc = _run(["xdotool", "windowclose", wid])
        if rc == 0:
            return {"closed": True}
        return {"closed": False, "reason": err}


class _WmctrlBackend:
    """Linux wmctrl fallback (works on some Wayland compositors via XWayland)."""

    def list_windows(self) -> list[dict[str, Any]]:
        out, _, rc = _run(["wmctrl", "-l"])
        if rc != 0:
            return []
        results = []
        for line in out.splitlines():
            parts = line.split(None, 3)
            if len(parts) >= 4:
                results.append({"id": parts[0], "title": parts[3]})
        return results

    def focus(self, title: str) -> dict[str, Any]:
        _, err, rc = _run(["wmctrl", "-a", title])
        if rc == 0:
            return {"focused": True, "title": title}
        return {"focused": False, "reason": err}

    def resize(self, title: str, width: int, height: int) -> dict[str, Any]:
        _, err, rc = _run(["wmctrl", "-r", title, "-e", f"0,-1,-1,{width},{height}"])
        if rc == 0:
            return {"resized": True, "width": width, "height": height}
        return {"resized": False, "reason": err}

    def close(self, title: str) -> dict[str, Any]:
        _, err, rc = _run(["wmctrl", "-c", title])
        if rc == 0:
            return {"closed": True}
        return {"closed": False, "reason": err}


class _NoOpBackend:
    """Safe no-op when no backend is available."""

    def list_windows(self) -> list[dict[str, Any]]:
        log.warning("[window_manager] no backend available — list_windows no-op")
        return []

    def focus(self, title: str) -> dict[str, Any]:
        log.warning("[window_manager] no backend available — focus no-op")
        return {"focused": False, "reason": "no_backend"}

    def resize(self, title: str, width: int, height: int) -> dict[str, Any]:
        return {"resized": False, "reason": "no_backend"}

    def close(self, title: str) -> dict[str, Any]:
        return {"closed": False, "reason": "no_backend"}


# ── public facade ────────────────────────────────────────────────────────────

def _pick_backend():
    system = platform.system()
    if system == "Windows":
        try:
            import win32gui  # noqa: F401
            return _Win32Backend()
        except ImportError:
            pass
    if system == "Darwin" and shutil.which("osascript"):
        return _MacOSBackend()
    if shutil.which("xdotool"):
        return _XdotoolBackend()
    if shutil.which("wmctrl"):
        return _WmctrlBackend()
    log.warning(
        "[window_manager] no backend found. Install xdotool (Linux) or wmctrl as fallback."
    )
    return _NoOpBackend()


class WindowManager:
    """Unified window management API — frontend for all backends."""

    def __init__(self):
        self._backend = _pick_backend()
        log.debug("[window_manager] backend: %s", type(self._backend).__name__)

    def list_windows(self) -> list[dict[str, Any]]:
        """Return a list of visible windows as {title, id?, hwnd?}."""
        return self._backend.list_windows()

    def focus(self, title: str) -> dict[str, Any]:
        """Bring a window to the foreground by (partial) title."""
        return self._backend.focus(title)

    def resize(self, title: str, width: int, height: int) -> dict[str, Any]:
        """Resize a window to the given pixel dimensions."""
        return self._backend.resize(title, max(1, width), max(1, height))

    def close(self, title: str) -> dict[str, Any]:
        """Close a window by title."""
        return self._backend.close(title)
