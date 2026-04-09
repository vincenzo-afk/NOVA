"""Offline TTS via pyttsx3."""

from __future__ import annotations

import queue
import threading
import time
import os

_QUEUE: queue.Queue | None = None
_WORKER_THREAD: threading.Thread | None = None
_WORKER_DISABLED: bool = False
_WORKER_LOCK = threading.Lock()

def _tts_worker() -> None:
    import pyttsx3
    try:
        engine = pyttsx3.init()
    except Exception:
        return
        
    while True:
        try:
            item = _QUEUE.get(timeout=1.0)
        except queue.Empty:
            continue
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
    global _QUEUE, _WORKER_THREAD, _WORKER_DISABLED
    with _WORKER_LOCK:
        if _WORKER_DISABLED:
            return
        try:
            import pyttsx3  # noqa: F401
        except Exception:
            _WORKER_DISABLED = True
            return
        # In pytest, rebuild worker per test case to avoid cross-test shared queue state.
        if os.getenv("PYTEST_CURRENT_TEST"):
            old_queue = _QUEUE
            old_thread = _WORKER_THREAD
            if old_queue is not None:
                try:
                    old_queue.put(None)
                except Exception:
                    pass
            if old_thread is not None:
                try:
                    old_thread.join(timeout=1.0)
                except Exception:
                    pass
            _WORKER_THREAD = None
            _QUEUE = None
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
    q = _QUEUE
    worker = _WORKER_THREAD
    if q is None or worker is None or not worker.is_alive():
        return
    done_event = threading.Event()
    q.put((text, done_event))
    started = time.monotonic()
    while not done_event.is_set():
        if stop_event is not None and stop_event.is_set():
            break
        if (time.monotonic() - started) > 15.0:
            break
        time.sleep(0.05)


def shutdown(drain: bool = True) -> None:
    """Best-effort worker stop for app shutdown paths."""
    global _QUEUE, _WORKER_THREAD
    if _QUEUE is None:
        return
    if drain:
        while True:
            try:
                _QUEUE.get_nowait()
                _QUEUE.task_done()
            except queue.Empty:
                break
            except Exception:
                break
    try:
        _QUEUE.put_nowait(None)
    except Exception:
        pass
    try:
        if _WORKER_THREAD is not None and _WORKER_THREAD.is_alive():
            _WORKER_THREAD.join(timeout=1.0)
    except Exception:
        pass
