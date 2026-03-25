"""API-key registry with simple provider detection."""

from __future__ import annotations


class MasterAPI:
    def __init__(self):
        self._keys: dict[str, str] = {}

    @staticmethod
    def detect_service(api_key: str) -> str:
        key = api_key.strip()
        if key.startswith(("ghp_", "github_pat_")):
            return "github"
        if key.startswith("xoxb-") or key.startswith("xapp-"):
            return "slack"
        if key.startswith("ntn_") or key.startswith("secret_"):
            return "notion"
        if key.startswith("sk-"):
            return "openai"
        if key.startswith("AIza"):
            return "google"
        return "custom"

    def register(self, service: str, api_key: str) -> None:
        svc = (service or "").strip().lower() or self.detect_service(api_key)
        self._keys[svc] = api_key.strip()

    def get(self, service: str) -> str | None:
        return self._keys.get(service.lower())

    def list_services(self) -> list[str]:
        return sorted(self._keys)
