"""Screenshot capture utilities — Feature 12 (mss Wayland fallback).

Backend selection priority:
  1. mss            — works on X11, Wayland, Windows, macOS
  2. PIL.ImageGrab   — works on X11 / Windows / macOS (breaks on Wayland)
  3. scrot           — Linux X11/Wayland CLI fallback
  4. afplay/ffmpeg   — not used here but noted for audio parity

The backend is chosen once at import time based on what is installed.
"""
from __future__ import annotations

import io
import logging
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from typing import Generator

log = logging.getLogger(__name__)


# ── backend selection ─────────────────────────────────────────────────────────

def _pick_screenshot_backend() -> str:
    try:
        import mss  # noqa: F401
        return "mss"
    except ImportError:
        pass
    try:
        from PIL import ImageGrab  # noqa: F401
        return "pil"
    except ImportError:
        pass
    if shutil.which("scrot"):
        return "scrot"
    log.warning(
        "[capture] No screenshot backend found. "
        "Install 'mss' (pip install mss) to enable screen capture."
    )
    return "none"


_BACKEND = _pick_screenshot_backend()


def _to_png_bytes(image) -> bytes:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


# ── per-backend capture ───────────────────────────────────────────────────────

def _capture_full_mss() -> bytes:
    import mss
    import mss.tools

    with mss.mss() as sct:
        monitor = sct.monitors[0]  # 0 = entire virtual screen
        shot = sct.grab(monitor)
        return mss.tools.to_png(shot.rgb, shot.size)


def _capture_region_mss(x: int, y: int, width: int, height: int) -> bytes:
    import mss
    import mss.tools

    with mss.mss() as sct:
        mon = {"left": x, "top": y, "width": max(1, width), "height": max(1, height)}
        shot = sct.grab(mon)
        return mss.tools.to_png(shot.rgb, shot.size)


def _capture_full_pil() -> bytes:
    from PIL import ImageGrab
    return _to_png_bytes(ImageGrab.grab())


def _capture_region_pil(x: int, y: int, width: int, height: int) -> bytes:
    from PIL import ImageGrab
    bbox = (x, y, x + max(1, width), y + max(1, height))
    return _to_png_bytes(ImageGrab.grab(bbox=bbox))


def _capture_full_scrot() -> bytes:
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        path = f.name
    try:
        subprocess.run(["scrot", path], check=True, timeout=5)
        return Path(path).read_bytes()
    finally:
        try:
            os.unlink(path)
        except Exception:
            pass


# ── public API ────────────────────────────────────────────────────────────────

def capture_screen_png() -> bytes:
    """Capture the entire screen as PNG bytes using the best available backend."""
    if _BACKEND == "mss":
        return _capture_full_mss()
    if _BACKEND == "pil":
        return _capture_full_pil()
    if _BACKEND == "scrot":
        return _capture_full_scrot()
    raise RuntimeError(
        "No screenshot backend available. Install mss: pip install mss"
    )


def capture_region_png(x: int, y: int, width: int, height: int) -> bytes:
    """Capture a screen region as PNG bytes."""
    if _BACKEND == "mss":
        return _capture_region_mss(x, y, width, height)
    if _BACKEND == "pil":
        return _capture_region_pil(x, y, width, height)
    # scrot doesn't support region easily; fall back to full capture
    if _BACKEND == "scrot":
        log.debug("[capture] scrot: region capture → full screen fallback")
        return _capture_full_scrot()
    raise RuntimeError("No screenshot backend available.")


def capture_active_window_png() -> bytes:
    """Capture the active window, falling back to full screen."""
    try:
        import pyautogui
        window = pyautogui.getActiveWindow()
        if window:
            return capture_region_png(
                window.left, window.top, window.width, window.height
            )
    except Exception:
        pass
    return capture_screen_png()


def capture_periodic_png(
    interval_seconds: float = 2.0,
) -> Generator[bytes, None, None]:
    """Yield PNG screenshots forever at the given interval."""
    while True:
        yield capture_screen_png()
        time.sleep(max(0.1, interval_seconds))
