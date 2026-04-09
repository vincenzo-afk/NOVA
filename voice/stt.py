"""Online speech-to-text adapter."""

from __future__ import annotations

import base64
import json
from typing import Iterable

import requests

from config.settings import settings


def _iter_api_keys() -> Iterable[str]:
    for key in settings.GEMINI_API_KEYS:
        cleaned = key.strip()
        if cleaned:
            yield cleaned


def _guess_mime(audio_bytes: bytes) -> str:
    if audio_bytes.startswith(b"RIFF") and b"WAVE" in audio_bytes[:16]:
        return "audio/wav"
    if audio_bytes.startswith(b"ID3") or audio_bytes[:2] == b"\xff\xfb":
        return "audio/mpeg"
    return "application/octet-stream"


def _extract_text(payload: dict) -> str:
    candidates = payload.get("candidates", [])
    if not candidates:
        return ""

    parts = candidates[0].get("content", {}).get("parts", [])
    text = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
    return text.strip()


def transcribe(audio_bytes: bytes, lang: str = "en") -> str:
    if not audio_bytes:
        return ""

    instruction = (
        "Transcribe this spoken audio accurately. "
        f"Preferred language hint: {lang}. "
        "Return plain transcription text only. No formatting, no extra commentary."
    )
    body = {
        "contents": [
            {
                "parts": [
                    {"text": instruction},
                    {
                        "inline_data": {
                            "mime_type": _guess_mime(audio_bytes),
                            "data": base64.b64encode(audio_bytes).decode("ascii"),
                        }
                    },
                ]
            }
        ],
        "generationConfig": {"temperature": 0.0},
    }

    for api_key in _iter_api_keys():
        try:
            response = None
            for _attempt in range(2):
                response = requests.post(
                    "https://generativelanguage.googleapis.com/v1beta/models/"
                    f"gemini-2.0-flash:generateContent?key={api_key}",
                    headers={"Content-Type": "application/json"},
                    data=json.dumps(body),
                    timeout=45,
                )
                if response.ok:
                    break
                if response.status_code >= 500:
                    import time as _t
                    _t.sleep(0.5 * (_attempt + 1))
                    continue
                break
            if response is None:
                continue
            if not response.ok:
                continue
            text = _extract_text(response.json())
            if text:
                return text
        except Exception:
            continue
    return ""
