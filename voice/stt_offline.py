"""Offline speech-to-text via faster-whisper."""

from __future__ import annotations

import os
import tempfile


class OfflineWhisper:
    def __init__(self, model_size: str = "base"):
        self.model_size = model_size
        self._model = None

    def _load(self):
        if self._model is None:
            from faster_whisper import WhisperModel

            self._model = WhisperModel(self.model_size, device="cpu", compute_type="int8")

    def transcribe(self, audio_bytes: bytes, lang: str = "en") -> str:
        if not audio_bytes:
            return ""
        self._load()
        # Use delete=False so the file can be read on all platforms (inc. Windows)
        tmp_path = ""
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                f.write(audio_bytes)
                tmp_path = f.name
            try:
                segments, _ = self._model.transcribe(tmp_path, language=lang)
            except Exception:
                # Re-try without language hint if the code is unrecognised
                segments, _ = self._model.transcribe(tmp_path)
            return " ".join(seg.text for seg in segments).strip()
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
