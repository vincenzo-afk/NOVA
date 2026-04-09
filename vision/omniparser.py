"""OmniParser HTTP client — sends base64 JSON to match server's ParseRequest schema.

Fix 6.2: Previous version sent multipart/form-data but the server expects
         {"base64_image": "<base64 string>"}. Every call was silently returning
         empty results with a 422 Unprocessable Entity.
"""

from __future__ import annotations

import base64
import time
import hashlib
from collections import OrderedDict

import requests


_UI_ELEMENT_CACHE: OrderedDict[str, tuple[float, list[dict]]] = OrderedDict()
_UI_ELEMENT_CACHE_TTL_S = 0.5  # fix 3.2: 500 ms TTL


def clear_ui_element_cache() -> None:
    _UI_ELEMENT_CACHE.clear()


class OmniParserClient:
    def __init__(self, base_url: str = "http://localhost:8000", auth_token: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.auth_token = auth_token

    def parse(self, image_bytes: bytes) -> dict:
        """POST base64-encoded image to /parse/ and return parsed payload."""
        encoded = base64.b64encode(image_bytes).decode("ascii")
        headers = {}
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"
        response = requests.post(
            f"{self.base_url}/parse/",
            json={"base64_image": encoded},
            timeout=60,
            headers=headers,
        )
        response.raise_for_status()
        return response.json()

    def ocr_text(self, image_bytes: bytes) -> str:
        try:
            payload = self.parse(image_bytes)
        except Exception:
            return ""
        lines = payload.get("ocr_text") or payload.get("text") or []
        if isinstance(lines, list):
            return "\n".join(str(line) for line in lines if line)
        return str(lines or "")

    def ui_elements(self, image_bytes: bytes) -> list[dict]:
        """Return UI elements with short-TTL caching to avoid per-click screenshot round-trips (fix 3.2)."""
        key_material = (self.auth_token or "") + "|" + hashlib.sha256(image_bytes).hexdigest()
        cache_key = hashlib.sha256(key_material.encode("utf-8")).hexdigest()
        now = time.monotonic()
        if cache_key in _UI_ELEMENT_CACHE:
            cached_time, cached_elements = _UI_ELEMENT_CACHE[cache_key]
            if now - cached_time < _UI_ELEMENT_CACHE_TTL_S:
                return cached_elements

        try:
            payload = self.parse(image_bytes)
        except Exception:
            return []
        elements = payload.get("elements") or payload.get("ui_elements") or []
        result = [e for e in elements if isinstance(e, dict)]
        _UI_ELEMENT_CACHE[cache_key] = (now, result)
        if len(_UI_ELEMENT_CACHE) > 10:
            _UI_ELEMENT_CACHE.popitem(last=False)
        return result
