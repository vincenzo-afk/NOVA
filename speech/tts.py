"""Offline TTS via pyttsx3."""

from __future__ import annotations

import queue
import threading
import time

_QUEUE: queue.Queue | None = None
_WORKER_THREAD: threading.Thread | None = None


def _tts_worker() -> None:
    import pyttsx3
    try:
        engine = pyttsx3.init()
    except Exception:
        return

    while True:
        try:
            item = _QUEUE.get()
        except Exception:
            continue

        if item is None:
            _QUEUE.task_done()
            break

        text, done_event = item
        try:
            engine.say(text)
            engine.runAndWait()
        except Exception:
            pass
        finally:
            done_event.set()
            _QUEUE.task_done()


def _ensure_worker() -> None:
    global _QUEUE, _WORKER_THREAD
    if _QUEUE is None:
        _QUEUE = queue.Queue()
    if _WORKER_THREAD is None or not _WORKER_THREAD.is_alive():
        _WORKER_THREAD = threading.Thread(target=_tts_worker, daemon=True)
        _WORKER_THREAD.start()


def speak(text: str, stop_event: threading.Event | None = None) -> None:
    """Queue text for speech and block until done or stopped."""
    if not text.strip():
        return

    _ensure_worker()
    done_event = threading.Event()
    _QUEUE.put((text, done_event))

    while not done_event.is_set():
        if stop_event is not None and stop_event.is_set():
            break
        time.sleep(0.05)
