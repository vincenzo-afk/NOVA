"""OmniParser HTTP client."""

from __future__ import annotations

import requests


class OmniParserClient:
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url.rstrip("/")

    def parse(self, image_bytes: bytes) -> dict:
        response = requests.post(
            f"{self.base_url}/parse",
            files={"file": ("screen.png", image_bytes, "image/png")},
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    def ocr_text(self, image_bytes: bytes) -> str:
        payload = self.parse(image_bytes)
        lines = payload.get("ocr_text") or payload.get("text") or []
        if isinstance(lines, list):
            return "\n".join(str(line) for line in lines if line)
        return str(lines or "")

    def ui_elements(self, image_bytes: bytes) -> list[dict]:
        payload = self.parse(image_bytes)
        elements = payload.get("elements") or payload.get("ui_elements") or []
        if isinstance(elements, list):
            return [e for e in elements if isinstance(e, dict)]
        return []
