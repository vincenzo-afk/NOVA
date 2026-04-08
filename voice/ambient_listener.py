"""Ambient audio monitor with lightweight event detection (Phase 16)."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable


@dataclass
class AmbientEvent:
    event_type: str
    confidence: float
    detail: str = ""


class AmbientListener:
    def __init__(
        self,
        *,
        keywords: list[str] | None = None,
        on_event: Callable[[AmbientEvent], None] | None = None,
        sample_rate: int = 16_000,
        frame_seconds: float = 0.5,
    ):
        self.keywords = [k.strip().lower() for k in (keywords or []) if k.strip()]
        self.on_event = on_event
        self.sample_rate = max(8_000, int(sample_rate))
        self.frame_seconds = max(0.2, float(frame_seconds))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_event_at = 0.0

    def start(self) -> None:
        if self.is_running():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _run(self) -> None:
        # No audio is stored; each frame is discarded after feature extraction.
        try:
            import numpy as np
            import sounddevice as sd
        except Exception:
            return

        frame_samples = max(1, int(self.sample_rate * self.frame_seconds))
        with sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
            blocksize=frame_samples,
        ) as stream:
            ring_pattern_hits = 0
            while not self._stop.is_set():
                chunk, overflow = stream.read(frame_samples)
                if overflow:
                    continue
                frame = np.asarray(chunk, dtype=np.float32).reshape(-1)
                if frame.size == 0:
                    continue

                energy = float(np.mean(np.abs(frame)))
                # Detect sharp tonal events using FFT peak prominence.
                spectrum = np.abs(np.fft.rfft(frame))
                if spectrum.size < 8:
                    continue
                peak_idx = int(np.argmax(spectrum))
                peak_val = float(spectrum[peak_idx])
                mean_val = float(np.mean(spectrum) + 1e-8)
                dominance = peak_val / mean_val
                freq = (peak_idx * self.sample_rate) / max(1, (2 * (spectrum.size - 1)))

                if energy > 0.02 and dominance > 8.0 and 600 <= freq <= 3000:
                    ring_pattern_hits += 1
                else:
                    ring_pattern_hits = max(0, ring_pattern_hits - 1)

                if ring_pattern_hits >= 3:
                    self._emit("ring_or_alarm", 0.72, f"peak_freq={int(freq)}Hz")
                    ring_pattern_hits = 0

                # Keyword matching placeholder: if user configured keywords, emit low-confidence
                # ambient_text_event when sustained voice-like energy is seen.
                if self.keywords and energy > 0.03 and dominance < 3.5:
                    self._emit("ambient_keyword_possible", 0.35, ",".join(self.keywords[:3]))

                time.sleep(0.02)

    def _emit(self, event_type: str, confidence: float, detail: str) -> None:
        now = time.time()
        if now - self._last_event_at < 10.0:
            return
        self._last_event_at = now
        if self.on_event is None:
            return
        try:
            self.on_event(AmbientEvent(event_type=event_type, confidence=float(confidence), detail=detail))
        except Exception:
            pass
