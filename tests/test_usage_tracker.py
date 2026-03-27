from __future__ import annotations

from datetime import date, timedelta

from interfaces.cli import format_usage_message
from utils.usage_tracker import UsageTracker


def test_weekly_summary_aggregates_multiple_days():
    tracker = UsageTracker()
    today = date.today()

    tracker.add("cloud", 10, 5, session_id="sess-1", when=today)
    tracker.add("cloud", 4, 1, session_id="sess-1", when=today - timedelta(days=2))
    tracker.add("local", 3, 2, session_id="sess-1", when=today - timedelta(days=6))
    tracker.add("cloud", 100, 100, session_id="other", when=today)

    weekly = tracker.weekly_summary(session_id="sess-1", end_date=today)

    assert weekly["cloud"]["total_tokens"] == 20
    assert weekly["local"]["total_tokens"] == 5
    assert tracker.total_tokens_week(session_id="sess-1", end_date=today) == 25


def test_today_summary_stays_scoped_to_today():
    tracker = UsageTracker()
    today = date.today()

    tracker.add("cloud", 2, 3, session_id="sess-1", when=today)
    tracker.add("cloud", 8, 9, session_id="sess-1", when=today - timedelta(days=1))

    today_summary = tracker.today_summary(session_id="sess-1")

    assert today_summary["cloud"]["total_tokens"] == 5


def test_format_usage_message_is_human_readable():
    text = format_usage_message(
        "Usage this week",
        {"cloud": {"input_tokens": 12, "output_tokens": 8, "total_tokens": 20}},
    )
    assert "Usage this week" in text
    assert "cloud: input=12 output=8 total=20" in text
