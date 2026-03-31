"""macOS permission checker — Feature 16.

Checks Accessibility and Screen Recording entitlements at startup.
These are required for mouse/keyboard automation and screen capture.
On non-macOS systems this module is a no-op.
"""
from __future__ import annotations

import logging
import platform

log = logging.getLogger(__name__)

_ACCESSIBILITY_URL = (
    "System Settings → Privacy & Security → Accessibility → enable your terminal / Python"
)
_SCREEN_RECORDING_URL = (
    "System Settings → Privacy & Security → Screen Recording → enable your terminal / Python"
)


def _check_accessibility() -> bool:
    """Return True if Accessibility is granted. Best-effort."""
    try:
        from AppKit import NSWorkspace  # type: ignore[import]
        _ = NSWorkspace  # just importing is enough to test availability
    except ImportError:
        pass  # PyObjC not installed — skip, PyAutoGUI will give its own error
        return True

    try:
        import ctypes, ctypes.util  # noqa: E401

        AX = ctypes.cdll.LoadLibrary(
            ctypes.util.find_library("ApplicationServices") or ""
        )
        # AXIsProcessTrusted() → 1 if Accessibility is granted
        AX.AXIsProcessTrusted.restype = ctypes.c_bool
        return bool(AX.AXIsProcessTrusted())
    except Exception:
        return True  # can't determine; assume OK so we don't block startup


def _check_screen_recording() -> bool:
    """Return True if Screen Recording is granted. Best-effort."""
    try:
        import Quartz  # type: ignore[import]

        # CGWindowListCopyWindowInfo returns an empty list when screen recording
        # is denied (returns None or empty CFArray).
        info = Quartz.CGWindowListCopyWindowInfo(
            Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID
        )
        # If the list exists and has at least one entry we have permission.
        return bool(info and len(info) > 0)
    except Exception:
        return True  # Quartz not importable → assume OK


def check_permissions(warn_only: bool = True) -> dict[str, bool]:
    """Check macOS permissions.  Returns {permission: granted}.

    Called at NOVAApp startup on Darwin.  Logs warnings for missing permissions
    with direct links to the System Settings pane.
    Only runs on macOS; returns {} on all other platforms.
    """
    if platform.system() != "Darwin":
        return {}

    results: dict[str, bool] = {}

    ax_ok = _check_accessibility()
    results["accessibility"] = ax_ok
    if not ax_ok:
        log.warning(
            "[macOS] Accessibility permission MISSING — mouse/keyboard automation will fail.\n"
            "  → Grant access: %s",
            _ACCESSIBILITY_URL,
        )

    sr_ok = _check_screen_recording()
    results["screen_recording"] = sr_ok
    if not sr_ok:
        log.warning(
            "[macOS] Screen Recording permission MISSING — screenshots will fail.\n"
            "  → Grant access: %s",
            _SCREEN_RECORDING_URL,
        )

    if ax_ok and sr_ok:
        log.debug("[macOS] Accessibility ✓  Screen Recording ✓")

    return results
