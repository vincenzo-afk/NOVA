from __future__ import annotations

from utils.goals import format_goal_list


def test_format_goal_list_empty():
    assert format_goal_list([]) == "No goals queued."


def test_format_goal_list_renders_goal_rows():
    text = format_goal_list(
        [
            {
                "id": "goal_1",
                "goal": "Write summary",
                "status": "paused",
                "cursor": 3,
                "steps": [{"tool": "web.search"}],
            }
        ]
    )
    assert "goal_1" in text
    assert "paused" in text
    assert "step 3/1" in text
    assert "Write summary" in text
