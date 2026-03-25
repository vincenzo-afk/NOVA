"""Vision analysis adapter."""

from __future__ import annotations

import base64
import json
import re

import requests

from config.settings import settings


def _default_response() -> dict:
    return {
        "scene_type": "unknown",
        "detected_errors": [],
        "active_app": "unknown",
        "notable_elements": [],
        "suggested_actions": [],
    }


def _extract_text(payload: dict) -> str:
    candidates = payload.get("candidates", [])
    if not candidates:
        return ""
    parts = candidates[0].get("content", {}).get("parts", [])
    return "".join(part.get("text", "") for part in parts if isinstance(part, dict)).strip()


def _extract_json(text: str) -> dict | None:
    if not text:
        return None
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def _normalize(data: dict | None) -> dict:
    base = _default_response()
    if not isinstance(data, dict):
        return base
    for key in base:
        if key in data:
            base[key] = data[key]
    for key in ("detected_errors", "notable_elements", "suggested_actions"):
        if not isinstance(base[key], list):
            base[key] = [str(base[key])]
    base["scene_type"] = str(base["scene_type"])
    base["active_app"] = str(base["active_app"])
    return base


def analyze_image(image_bytes: bytes) -> dict:
    if not image_bytes:
        return _default_response()

    prompt = (
        "Analyze this screenshot and return ONLY valid JSON with exactly these keys: "
        "scene_type (string), detected_errors (string[]), active_app (string), "
        "notable_elements (string[]), suggested_actions (string[])."
    )
    request_data = {
        "contents": [
            {
                "parts": [
                    {"text": prompt},
                    {
                        "inline_data": {
                            "mime_type": "image/png",
                            "data": base64.b64encode(image_bytes).decode("ascii"),
                        }
                    },
                ]
            }
        ],
        "generationConfig": {"temperature": 0.1},
    }

    for api_key in settings.GEMINI_API_KEYS:
        api_key = api_key.strip()
        if not api_key:
            continue
        try:
            response = requests.post(
                "https://generativelanguage.googleapis.com/v1beta/models/"
                f"gemini-2.0-flash:generateContent?key={api_key}",
                headers={"Content-Type": "application/json"},
                data=json.dumps(request_data),
                timeout=30,
            )
            if not response.ok:
                continue
            payload = response.json()
            text = _extract_text(payload)
            parsed = _extract_json(text)
            return _normalize(parsed)
        except Exception:
            continue

    return _default_response()
