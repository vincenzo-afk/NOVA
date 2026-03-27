from __future__ import annotations

from utils.events import format_event_log


def test_format_event_log_empty():
    assert format_event_log([]) == "No recent alerts."


def test_format_event_log_renders_messages():
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
