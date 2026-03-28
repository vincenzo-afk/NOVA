"""Proactive screen watcher loop with rate-limited alerts."""

from __future__ import annotations

import threading
import time
from typing import Callable

from core.llm.fallback import NetworkState
from core.think.reasoning import detect_prompt_injection
from vision.capture import capture_screen_png
from vision.gemini_vision import analyze_image
from vision.omniparser import OmniParserClient


_ERROR_KEYWORDS = {
    "error",
    "exception",
    "traceback",
    "stack trace",
    "crash",
    "failed",
    "not responding",
    "permission denied",
    "fatal",
}


class ScreenWatcher:
    def __init__(
        self,
        interval_seconds: float = 6.0,
        cooldown_seconds: float = 120.0,
        on_alert: Callable[[str], None] | None = None,
        omniparser_url: str = "http://localhost:8000",
    ):
        self.interval_seconds = max(1.0, float(interval_seconds))
        self.cooldown_seconds = max(10.0, float(cooldown_seconds))
        self.on_alert = on_alert or (lambda msg: print(msg))
        self.omniparser = OmniParserClient(omniparser_url)
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._last_alert_ts = 0.0
        self._last_seen_summary = ""

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.is_running():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

    def restart(self) -> None:
        self.stop()
        self.start()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception:
                pass
            time.sleep(self.interval_seconds)

    def _tick(self) -> None:
        image_bytes = capture_screen_png()
        analysis = {}
        ocr_text = ""

        if NetworkState.is_online():
            analysis = analyze_image(image_bytes)
        else:
            try:
                ocr_text = self.omniparser.ocr_text(image_bytes)
            except Exception:
                ocr_text = ""

        message = self._detect_issue(analysis, ocr_text)
        if not message:
            return

        now = time.time()
        if now - self._last_alert_ts < self.cooldown_seconds:
            return
        if message == self._last_seen_summary:
            return

        self._last_alert_ts = now
        self._last_seen_summary = message
        self.on_alert(message)

    def _detect_issue(self, analysis: dict, ocr_text: str) -> str:
        errors = analysis.get("detected_errors") if isinstance(analysis, dict) else None
        if errors:
            text = ", ".join(str(e) for e in errors if e)
            if text:
                return f"I see an error on screen: {text}. Want me to help?"

        combined = " ".join(
            [
                str(analysis.get("scene_type", "")),
                str(analysis.get("active_app", "")),
                " ".join(str(x) for x in analysis.get("notable_elements", []) or []),
                " ".join(str(x) for x in analysis.get("suggested_actions", []) or []),
                ocr_text,
            ]
        ).lower()

        if detect_prompt_injection(combined):
            return ""

        if any(keyword in combined for keyword in _ERROR_KEYWORDS):
            return "I detected a possible error dialog on your screen. Want me to take a look?"

        return ""
