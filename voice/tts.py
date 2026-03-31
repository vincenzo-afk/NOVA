"""Online text-to-speech adapter with Gemini-first behavior."""

from __future__ import annotations

import contextlib
import base64
import json
import subprocess
import tempfile
import threading
import time
from typing import Any, Iterable

import requests

from config.settings import settings


def _play(path: str, stop_event: threading.Event | None = None) -> None:
    for cmd in (["afplay", path], ["mpg123", "-q", path], ["ffplay", "-nodisp", "-autoexit", path]):
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                while proc.poll() is None:
                    if stop_event is not None and stop_event.is_set():
                        proc.terminate()
                        break
                    time.sleep(0.05)
                if proc.poll() is None:
                    proc.wait(timeout=1)
            finally:
                if proc.poll() is None:
                    proc.kill()
            return
        except Exception:
            continue


def _iter_gemini_keys() -> Iterable[str]:
    for key in settings.GEMINI_API_KEYS:
        cleaned = key.strip()
        if cleaned:
            yield cleaned


def _emotion_hint(emotion: str) -> str:
    lookup = {
        "neutral": "calm and clear",
        "focused": "professional and focused",
        "concerned": "gentle and concerned",
        "enthusiastic": "upbeat and energetic",
        "cautious": "careful and measured",
        "empathetic": "warm and empathetic",
        "urgent": "urgent but controlled",
    }
    return lookup.get((emotion or "").strip().lower(), "natural and clear")


def build_tts_prompt(text: str, emotion: str = "neutral", lang: str = "en") -> str:
    style = _emotion_hint(emotion)
    return (
        "Read this message aloud. "
        f"Language: {lang}. "
        f"Speaking style: {style}. "
        "Output voice audio only.\n\n"
        f"{text}"
    )


def extract_audio_bytes(payload: dict[str, Any]) -> bytes:
    candidates = payload.get("candidates", [])
    if not isinstance(candidates, list):
        return b""

    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        content = candidate.get("content", {})
        parts = content.get("parts", []) if isinstance(content, dict) else []
        if not isinstance(parts, list):
            continue
        for part in parts:
            if not isinstance(part, dict):
                continue
            inline = part.get("inline_data") or part.get("inlineData")
            if isinstance(inline, dict):
                encoded = inline.get("data", "")
                if isinstance(encoded, str) and encoded:
                    try:
                        return base64.b64decode(encoded)
                    except Exception:
                        continue
            audio = part.get("audio")
            if isinstance(audio, str) and audio:
                try:
                    return base64.b64decode(audio)
                except Exception:
                    continue
    return b""


def _gemini_tts_bytes(text: str, emotion: str, lang: str) -> bytes:
    prompt = build_tts_prompt(text, emotion=emotion, lang=lang)
    model = settings.GEMINI_TTS_MODEL.strip() or "gemini-2.5-flash-preview-tts"
    voice_name = settings.GEMINI_TTS_VOICE.strip() or "Kore"
    timeout = max(5, int(settings.GEMINI_TTS_TIMEOUT_SECONDS))

    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {
                "voiceConfig": {
                    "prebuiltVoiceConfig": {"voiceName": voice_name}
                }
            },
        },
    }

    for api_key in _iter_gemini_keys():
        try:
            response = requests.post(
                "https://generativelanguage.googleapis.com/v1beta/models/"
                f"{model}:generateContent?key={api_key}",
                headers={"Content-Type": "application/json"},
                data=json.dumps(body),
                timeout=timeout,
            )
            if not response.ok:
                continue
            payload = response.json()
            audio_bytes = extract_audio_bytes(payload)
            if audio_bytes:
                return audio_bytes
        except Exception:
            continue

    return b""


def _speak_with_gtts(text: str, lang: str, stop_event: threading.Event | None = None) -> bool:
    try:
        from gtts import gTTS

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            path = tmp.name
        try:
            gTTS(text=text, lang=lang).save(path)
            _play(path, stop_event=stop_event)
            return True
        finally:
            with contextlib.suppress(Exception):
                import os

                os.unlink(path)
    except Exception:
        return False


def speak(
    text: str,
    emotion: str = "neutral",
    lang: str = "en",
    stop_event: threading.Event | None = None,
) -> None:
    clean = text.strip()
    if not clean:
        return

    audio_bytes = _gemini_tts_bytes(clean, emotion=emotion, lang=lang)
    if audio_bytes:
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp.write(audio_bytes)
                tmp.flush()
                path = tmp.name
            try:
                try:
                    _play(path, stop_event=stop_event)
                except TypeError:
                    try:
                        _play(path, stop_event)
                    except TypeError:
                        _play(path)
                return
            finally:
                with contextlib.suppress(Exception):
                    import os

                    os.unlink(path)
        except Exception:
            pass

    try:
        gtts_result = _speak_with_gtts(clean, lang=lang, stop_event=stop_event)
    except TypeError:
        # Compatibility path for legacy test doubles/helpers without stop_event.
        gtts_result = _speak_with_gtts(clean, lang=lang)
    if gtts_result:
        return

    # Fix 6.4: Try pyttsx3 as final fallback
    try:
        from voice.tts_offline import speak as offline_speak
        offline_speak(clean)
        return
    except Exception:
        pass

    print(f"[online-tts fallback {lang}/{emotion}] {clean}")
