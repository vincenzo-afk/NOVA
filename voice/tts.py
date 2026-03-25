"""Online text-to-speech adapter."""

from __future__ import annotations

import subprocess
import tempfile


def _play(path: str) -> None:
    for cmd in (["afplay", path], ["mpg123", "-q", path], ["ffplay", "-nodisp", "-autoexit", path]):
        try:
            subprocess.run(cmd, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except Exception:
            continue


def speak(text: str, emotion: str = "neutral", lang: str = "en") -> None:
    if not text.strip():
        return
    try:
        from gtts import gTTS

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=True) as tmp:
            gTTS(text=text, lang=lang).save(tmp.name)
            _play(tmp.name)
            return
    except Exception:
        pass
    print(f"[online-tts fallback {lang}/{emotion}] {text}")
