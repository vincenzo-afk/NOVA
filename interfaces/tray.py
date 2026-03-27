"""System tray controls with status, session, mute, and export actions."""

from __future__ import annotations

import threading
from typing import Any

from utils.events import format_event_log
from utils.goals import format_goal_list
from utils.health import summarize_health


def _format_k_tokens(tokens: int) -> str:
    if tokens >= 1_000_000:
        return f"{tokens / 1_000_000:.1f}M"
    if tokens >= 1_000:
        return f"{tokens / 1_000:.1f}k"
    return str(tokens)


def _format_goal_summary(agent: Any) -> str:
    try:
        goals = list(agent.list_goals())
    except Exception:
        goals = []
    if not goals:
        return "Goals: 0"

    counts: dict[str, int] = {}
    for goal in goals:
        status = str(goal.get("status", "unknown"))
        counts[status] = counts.get(status, 0) + 1
    parts = [f"{len(goals)} total"]
    for status in ("pending", "running", "paused", "completed", "failed", "cancelled"):
        if counts.get(status):
            parts.append(f"{counts[status]} {status}")
    return "Goals: " + " · ".join(parts)


def _format_health_summary(agent: Any) -> str:
    try:
        items = agent.health.status_table()
    except Exception:
        items = []
    summary = summarize_health(items)
    total = sum(summary.values())
    if total == 0:
        return "Health: unknown"
    parts = []
    for key in ("ok", "down", "restarting", "restart_failed", "unknown"):
        if summary.get(key):
            parts.append(f"{summary[key]} {key}")
    return "Health: " + " · ".join(parts)


def build_tray_title(agent: Any) -> str:
    state = "Online" if agent.memory.online else "Offline"
    session_id = getattr(agent.session.current, "session_id", "")
    tokens = 0
    try:
        tokens = int(agent.usage.total_tokens_today(session_id=session_id))
    except Exception:
        tokens = 0
    active_keys = 0
    try:
        active_keys = int(agent.engine.pool.active_count())
    except Exception:
        active_keys = 0
    muted = "Muted" if bool(getattr(agent, "is_muted", lambda: False)()) else "Live"
    goals = _format_goal_summary(agent)
    return (
        "Today: "
        f"{_format_k_tokens(tokens)} tokens · "
        f"{active_keys} keys active · "
        f"{state} · {muted} · {goals}"
    )


def run_tray(agent: Any) -> None:
    try:
        import pystray
        from PIL import Image, ImageDraw
    except Exception:  # pragma: no cover
        print("pystray/Pillow not installed; tray unavailable.")
        return

    icon_image = Image.new("RGB", (64, 64), color=(20, 28, 40))
    draw = ImageDraw.Draw(icon_image)
    draw.ellipse((12, 12, 52, 52), fill=(52, 211, 153))

    running = {"value": True}
    gui_thread = {"ref": None}

    def on_open_gui(_icon, _item):
        if gui_thread["ref"] is not None and gui_thread["ref"].is_alive():
            print("Tray action: GUI already running")
            return

        def _launch():
            try:
                from interfaces.gui.app import launch_gui

                launch_gui(agent)
            except Exception as exc:
                print(f"Tray action: failed to open GUI: {exc}")

        gui_thread["ref"] = threading.Thread(target=_launch, daemon=True)
        gui_thread["ref"].start()
        print("Tray action: opening GUI")

    def on_switch_work(_icon, _item):
        state = agent.switch_session("jarvis_work")
        print(f"Tray action: switched to {state.name}")

    def on_switch_personal(_icon, _item):
        state = agent.switch_session("jarvis_personal")
        print(f"Tray action: switched to {state.name}")

    def on_toggle_mute(_icon, _item):
        muted = bool(agent.toggle_mute())
        print("Tray action: muted" if muted else "Tray action: unmuted")

    def on_health(_icon, _item):
        try:
            print(agent.status_text())
        except Exception:
            try:
                print(_format_health_summary(agent))
                print(format_goal_list(agent.list_goals()))
            except Exception as exc:
                print(f"Tray action: health unavailable: {exc}")

    def on_goals(_icon, _item):
        try:
            print(format_goal_list(agent.list_goals()))
        except Exception as exc:
            print(f"Tray action: goals unavailable: {exc}")

    def on_alerts(_icon, _item):
        try:
            print(format_event_log(agent.recent_events()))
        except Exception as exc:
            print(f"Tray action: alerts unavailable: {exc}")

    def on_export(_icon, _item):
        try:
            path = agent.export_session("md")
            print(f"Tray action: exported session -> {path}")
        except Exception as exc:
            print(f"Tray action: export failed: {exc}")

    def on_quit(icon, _item):
        running["value"] = False
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("Open GUI", on_open_gui),
        pystray.MenuItem("Switch Session: Work", on_switch_work),
        pystray.MenuItem("Switch Session: Personal", on_switch_personal),
        pystray.MenuItem("Mute / Unmute", on_toggle_mute),
        pystray.MenuItem("Goals", on_goals),
        pystray.MenuItem("Alerts", on_alerts),
        pystray.MenuItem("Health", on_health),
        pystray.MenuItem("Export Session", on_export),
        pystray.MenuItem("Quit", on_quit),
    )
    icon = pystray.Icon("jarvis", icon_image, build_tray_title(agent), menu)

    def _keep_title_fresh():
        while running["value"]:
            icon.title = build_tray_title(agent)
            threading.Event().wait(10)

    threading.Thread(target=_keep_title_fresh, daemon=True).start()
    icon.run()
