"""API-key registry with provider detection and helpers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ServiceKey:
    service: str
    api_key: str


class MasterAPI:
    def __init__(self):
        self._keys: dict[str, ServiceKey] = {}

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

    def register(self, service: str, api_key: str) -> str:
        svc = (service or "").strip().lower() or self.detect_service(api_key)
        self._keys[svc] = ServiceKey(service=svc, api_key=api_key.strip())
        return svc

    def get(self, service: str) -> str | None:
        record = self._keys.get(service.lower())
        return record.api_key if record else None

    def masked(self, service: str) -> str | None:
        value = self.get(service)
        if not value:
            return None
        if len(value) <= 8:
            return "*" * len(value)
        return f"{value[:4]}...{value[-4:]}"

    def list_services(self) -> list[str]:
        return sorted(self._keys)
