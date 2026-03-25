from __future__ import annotations

from tasks.goals import GoalRun, detect_cycle


def test_detect_cycle_for_same_tool_and_args():
    previous = [("browser.open", {"url": "https://example.com"})]
    assert detect_cycle(previous, "browser.open", {"url": "https://example.com"})
    assert not detect_cycle(previous, "browser.open", {"url": "https://example.org"})


def test_goal_run_enforces_step_limit_and_cycle():
    run = GoalRun(max_steps=2)

    ok, reason = run.can_execute("tool.a", {"x": 1})
    assert ok and reason == "ok"
    run.record("tool.a", {"x": 1})

    ok, reason = run.can_execute("tool.a", {"x": 1})
    assert not ok
    assert "Cycle detected" in reason

    ok, _ = run.can_execute("tool.b", {"y": 2})
    assert ok
    run.record("tool.b", {"y": 2})

    ok, reason = run.can_execute("tool.c", {"z": 3})
    assert not ok
    assert "max_steps" in reason
