from __future__ import annotations

from core.health import HealthMonitor
from utils.health import format_health_table, summarize_health


def test_format_health_table_empty():
    assert format_health_table([]) == "Health: no subsystem data yet."


def test_format_health_table_renders_rows():
    text = format_health_table(
        [
            {
                "name": "scheduler",
                "status": "ok",
                "last_heartbeat": "2026-03-26T10:15:00",
            },
            {
                "name": "omniparser",
                "status": "down",
                "last_heartbeat": "2026-03-26T10:14:30",
            },
        ]
    )
    assert "scheduler | ok | 2026-03-26T10:15:00" in text
    assert "omniparser | down | 2026-03-26T10:14:30" in text


def test_summarize_health_counts_known_and_unknown_statuses():
    summary = summarize_health(
        [
            {"status": "ok"},
            {"status": "down"},
            {"status": "restarting"},
            {"status": "restart_failed"},
            {"status": "mystery"},
        ]
    )
    assert summary["ok"] == 1
    assert summary["down"] == 1
    assert summary["restarting"] == 1
    assert summary["restart_failed"] == 1
    assert summary["unknown"] == 1


def test_health_monitor_emits_state_changes_only():
    states = [False, False, True, True]
    events: list[tuple[str, str, str | None]] = []

    def check():
        return states.pop(0)

    monitor = HealthMonitor(on_change=lambda name, status, previous: events.append((name, status, previous)))
    monitor.register_subsystem("omniparser", check)

    monitor.poll_once()
    monitor.poll_once()
    monitor.poll_once()
    monitor.poll_once()

    assert events[0] == ("omniparser", "down", "unknown")
    assert events[1] == ("omniparser", "ok", "down")
