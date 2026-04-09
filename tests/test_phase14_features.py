from __future__ import annotations

from pathlib import Path

from config.settings import Settings
from core.memory.memory_router import MemoryRouter
from safety.virus_scanner import VirusScanner
from utils.theme_engine import choose_theme


class _DummyMem0:
    def __init__(self):
        self.calls = 0

    def add(self, text, session_id, metadata=None):
        self.calls += 1
        return {"status": "ok"}

    def get_all(self, session_id):
        return []


class _DummyLocal:
    def __init__(self):
        self.items = []

    def add(self, text, session_id, metadata=None):
        self.items.append((text, session_id, metadata or {}))
        return {"status": "ok", "id": f"id_{len(self.items)}"}

    def search(self, query, session_id, top_k=20):
        return []

    def get_all(self, session_id):
        return []


def test_settings_local_only_disables_cloud_flags():
    s = Settings(
        OPENAI_API_KEYS=["sk-real-key-12345678901234567890"],
        OPENAI_BASE_URL="https://api.openai.com",
        GEMINI_API_KEYS=["AIza-some-realistic-long-key-1234567890"],
        TELEGRAM_BOT_TOKEN="123:abc",
        TELEGRAM_CHAT_ID="999",
        PRIVACY_MODE="local_only",
    )
    assert s.has_cloud_llm is False
    assert s.has_gemini is False
    assert s.has_telegram is False


def test_memory_router_remote_sync_toggle_blocks_mem0_calls():
    mem0 = _DummyMem0()
    local = _DummyLocal()
    router = MemoryRouter(mem0=mem0, local=local)
    router.set_online(True)
    router.set_remote_sync_enabled(False)
    router.add("hello", "s1", {"source": "test"})
    assert mem0.calls == 0


def test_virus_scanner_flags_obvious_suspicious_buffer():
    scanner = VirusScanner(api_key="")
    text = "powershell -enc AAAA; reg add HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run"
    result = scanner.scan_text_buffer(text, filename="evil.ps1")
    assert result["safe"] is False
    assert result["detections"] >= 1


def test_theme_engine_urgent_wins():
    decision = choose_theme(hour=11, topic="reading", emotion="urgent", locked_theme="")
    assert decision.name == "urgent"


def test_virus_scanner_rejects_oversized_file(tmp_path: Path):
    target = tmp_path / "huge.bin"
    target.write_bytes(b"x" * 64)
    scanner = VirusScanner(api_key="", max_scan_bytes=32)
    result = scanner.scan_file(str(target))
    assert result["status"] == "error"
    assert result["reason"] == "file_too_large"
