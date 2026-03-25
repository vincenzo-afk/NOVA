"""Indic language TTS fallback."""

from __future__ import annotations

import tempfile


def speak_tamil(text: str) -> str:
    from gtts import gTTS

    tts = gTTS(text=text, lang="ta")
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        tts.save(f.name)
        return f.name
