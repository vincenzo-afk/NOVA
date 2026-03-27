"""Shared goal formatting helpers."""

from __future__ import annotations

from typing import Any


def format_goal_list(goals: list[dict[str, Any]]) -> str:
    if not goals:
        return "No goals queued."

    lines: list[str] = []
    for item in goals:
        goal_id = str(item.get("id", "unknown"))
        goal = str(item.get("goal", ""))
        status = str(item.get("status", "unknown"))
        cursor = int(item.get("cursor", 0))
        total_steps = len(item.get("steps") or [])
        lines.append(f"- {goal_id} | {status} | step {cursor}/{total_steps} | {goal}")
    return "\n".join(lines)
