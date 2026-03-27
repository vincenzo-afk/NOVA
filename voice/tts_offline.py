"""Offline TTS via pyttsx3."""

from __future__ import annotations

import threading
import time
from threading import Lock


_ENGINE = None
_LOCK = Lock()


def _engine():
    global _ENGINE
    if _ENGINE is None:
        import pyttsx3

        _ENGINE = pyttsx3.init()
    return _ENGINE


def speak(text: str, stop_event: threading.Event | None = None) -> None:
    if not text.strip():
        return
    with _LOCK:
        engine = _engine()
        done = threading.Event()

        def _run() -> None:
            try:
                engine.say(text)
                engine.runAndWait()
            finally:
                done.set()

        worker = threading.Thread(target=_run, daemon=True)
        worker.start()
        while not done.is_set():
            if stop_event is not None and stop_event.is_set():
                try:
                    engine.stop()
                except Exception:
                    pass
                break
            time.sleep(0.05)
        worker.join(timeout=1)
