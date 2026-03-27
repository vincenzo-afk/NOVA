from __future__ import annotations

from interfaces.tray import _format_k_tokens, build_tray_title


class _DummyPool:
    @staticmethod
    def active_count() -> int:
        return 3


class _DummyEngine:
    pool = _DummyPool()


class _DummySessionState:
    session_id = "s1"


class _DummySession:
    current = _DummySessionState()


class _DummyUsage:
    @staticmethod
    def total_tokens_today(session_id: str | None = None) -> int:
        _ = session_id
        return 42000


class _DummyMemory:
    online = True


class _DummyAgent:
    usage = _DummyUsage()
    session = _DummySession()
    memory = _DummyMemory()
    engine = _DummyEngine()

    @staticmethod
    def is_muted() -> bool:
        return False

    @staticmethod
    def list_goals():
        return [
            {"status": "paused"},
            {"status": "running"},
            {"status": "running"},
        ]


def test_format_k_tokens():
    assert _format_k_tokens(42) == "42"
    assert _format_k_tokens(42000) == "42.0k"
    assert _format_k_tokens(2_500_000) == "2.5M"


def test_build_tray_title():
    title = build_tray_title(_DummyAgent())
    assert "42.0k tokens" in title
    assert "3 keys active" in title
    assert "Online" in title
    assert "Goals:" in title
    assert "paused" in title
