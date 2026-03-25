"""Offline speech-to-text via faster-whisper."""

from __future__ import annotations

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
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as f:
            f.write(audio_bytes)
            f.flush()
            try:
                segments, _ = self._model.transcribe(f.name, language=lang)
            except Exception:
                segments, _ = self._model.transcribe(f.name)
            return " ".join(seg.text for seg in segments).strip()
