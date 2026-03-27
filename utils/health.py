"""Shared health formatting helpers."""

from __future__ import annotations

from typing import Any


def format_health_table(items: list[dict[str, Any]]) -> str:
    if not items:
        return "Health: no subsystem data yet."

    lines = ["Subsystem | Status | Last heartbeat", "--- | --- | ---"]
    for item in items:
        name = str(item.get("name", "unknown"))
        status = str(item.get("status", "unknown"))
        last = str(item.get("last_heartbeat", ""))
        lines.append(f"{name} | {status} | {last}")
    return "\n".join(lines)


def summarize_health(items: list[dict[str, Any]]) -> dict[str, int]:
    summary = {"ok": 0, "down": 0, "restarting": 0, "restart_failed": 0, "unknown": 0}
    for item in items:
        status = str(item.get("status", "unknown"))
        if status not in summary:
            summary["unknown"] += 1
        else:
            summary[status] += 1
    return summary
