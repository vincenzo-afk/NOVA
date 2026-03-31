from __future__ import annotations

from core.session import SessionManager


def test_session_manager_caps_history_length():
    sm = SessionManager(default_name="test", max_history_turns=50)
    for i in range(51):
        sm.add_turn("user", str(i))
    assert len(sm.current.history) == 50
    assert sm.current.history[0]["content"] == "1"
    assert sm.current.history[-1]["content"] == "50"
