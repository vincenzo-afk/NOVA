"""Screenshot capture utilities."""

from __future__ import annotations

from io import BytesIO
import time
from typing import Generator

from PIL import ImageGrab


def _to_png_bytes(image) -> bytes:
    buf = BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def capture_screen_png() -> bytes:
    return _to_png_bytes(ImageGrab.grab())


def capture_region_png(x: int, y: int, width: int, height: int) -> bytes:
    bbox = (x, y, x + max(1, width), y + max(1, height))
    return _to_png_bytes(ImageGrab.grab(bbox=bbox))


def capture_active_window_png() -> bytes:
    try:
        import pyautogui

        window = pyautogui.getActiveWindow()
        if window:
            return capture_region_png(window.left, window.top, window.width, window.height)
    except Exception:
        pass
    return capture_screen_png()


def capture_periodic_png(interval_seconds: float = 2.0) -> Generator[bytes, None, None]:
    while True:
        yield capture_screen_png()
        time.sleep(max(0.1, interval_seconds))
