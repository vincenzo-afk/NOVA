"""Offline TTS via pyttsx3."""

from __future__ import annotations

from threading import Lock


_ENGINE = None
_LOCK = Lock()


def _engine():
    global _ENGINE
    if _ENGINE is None:
        import pyttsx3

        _ENGINE = pyttsx3.init()
    return _ENGINE


def speak(text: str) -> None:
    if not text.strip():
        return
    with _LOCK:
        engine = _engine()
        engine.say(text)
        engine.runAndWait()
