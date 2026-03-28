"""Porcupine wake-word listener."""

from __future__ import annotations

import struct
import threading
import time
from typing import Callable

from config.settings import settings
from utils.logger import get_logger


class WakeWordListener:
    def __init__(self, callback: Callable[[], None]):
        self.callback = callback
        self._running = False
        self._active = False
        self._muted = False
        self._thread: threading.Thread | None = None
        self._log = get_logger(__name__)

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

    def set_muted(self, muted: bool) -> None:
        self._muted = muted

    def is_running(self) -> bool:
        return bool(self._running and self._active and self._thread and self._thread.is_alive())

    def _loop(self) -> None:
        if not settings.PORCUPINE_ACCESS_KEY or not settings.PORCUPINE_KEYWORD_PATH:
            self._log.warning(
                "Wake word disabled: PORCUPINE_ACCESS_KEY or PORCUPINE_KEYWORD_PATH is missing."
            )
            self._running = False
            return
        try:
            import pvporcupine
            import pyaudio
        except Exception as exc:
            self._log.warning("Wake word dependencies unavailable: %s", exc)
            self._running = False
            return

        porcupine = None
        pa = None
        stream = None
        try:
            porcupine = pvporcupine.create(
                access_key=settings.PORCUPINE_ACCESS_KEY,
                keyword_paths=[settings.PORCUPINE_KEYWORD_PATH],
                sensitivities=[settings.PORCUPINE_SENSITIVITY],
            )
            pa = pyaudio.PyAudio()
            stream = pa.open(
                rate=porcupine.sample_rate,
                channels=1,
                format=pyaudio.paInt16,
                input=True,
                frames_per_buffer=porcupine.frame_length,
            )
            self._active = True

            while self._running:
                if self._muted:
                    time.sleep(0.05)
                    continue

                pcm = stream.read(porcupine.frame_length, exception_on_overflow=False)
                frame = struct.unpack_from("h" * porcupine.frame_length, pcm)
                keyword_index = porcupine.process(frame)
                if keyword_index >= 0 and self._running and not self._muted:
                    self.callback()
        except Exception as exc:
            self._log.warning("Wake word loop stopped unexpectedly: %s", exc)
        finally:
            self._active = False
            self._running = False
            try:
                if stream is not None:
                    stream.stop_stream()
                    stream.close()
            except Exception:
                pass
            try:
                if pa is not None:
                    pa.terminate()
            except Exception:
                pass
            try:
                if porcupine is not None:
                    porcupine.delete()
            except Exception:
                pass
