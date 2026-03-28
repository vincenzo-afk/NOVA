from __future__ import annotations

from interfaces.gui.app import build_status_snapshot, format_status_line, format_usage_line
from utils.events import format_event_log


class _DummyPool:
    @staticmethod
    def active_count() -> int:
        return 2


class _DummyEngine:
    pool = _DummyPool()


class _DummySessionCurrent:
    name = "jarvis_work"
    session_id = "sess-1"


class _DummySession:
    current = _DummySessionCurrent()


class _DummyUsage:
    @staticmethod
    def total_tokens_today(session_id: str | None = None) -> int:
        _ = session_id
        return 1234


class _DummyAgent:
    session = _DummySession()
    usage = _DummyUsage()
    engine = _DummyEngine()
    emotion_state = "focused"

    @staticmethod
    def last_provider_label() -> str:
        return "cloud • key_1"

    @staticmethod
    def is_muted() -> bool:
        return False


def test_build_status_snapshot_contains_expected_keys():
    snapshot = build_status_snapshot(_DummyAgent())
    assert snapshot["session"] == "jarvis_work"
    assert snapshot["provider"] == "cloud • key_1"
    assert snapshot["emotion"] == "focused"
    assert snapshot["tokens_today"] == 1234
    assert snapshot["active_keys"] == 2


def test_status_and_usage_lines_are_human_readable():
    snapshot = {
        "session": "jarvis_personal",
        "online": True,
        "emotion": "neutral",
        "provider": "local • ollama",
        "muted": True,
        "tokens_today": 200,
        "active_keys": 1,
    }
    status_line = format_status_line(snapshot)
    usage_line = format_usage_line(snapshot)
    assert "Session: jarvis_personal" in status_line
    assert "Provider: local • ollama" in status_line
    assert "Alerts: Muted" in status_line
    assert usage_line == "Today: 200 tokens | Active cloud keys: 1"


def test_format_event_log_renders_entries():
    text = format_event_log(
        [
            {"kind": "proactive", "message": "Screen error", "timestamp": 1700000000},
            {"kind": "autonomy", "message": "Goal paused", "timestamp": 1700000100},
        ]
    )
    assert "Screen error" in text
    assert "Goal paused" in text
    assert "Proactive" in text
    assert "Autonomy" in text
