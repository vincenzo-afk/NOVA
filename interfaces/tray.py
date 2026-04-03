"""System tray controls with status, session, mute, and export actions."""

from __future__ import annotations

import threading
from typing import Any

from control import os_layer
from config.constants import DEFAULT_SESSION_PERSONAL, DEFAULT_SESSION_WORK
from utils.events import format_event_log
from utils.goals import format_goal_list
from utils.health import summarize_health


def _format_k_tokens(tokens: int) -> str:
    if tokens >= 1_000_000:
        return f"{tokens / 1_000_000:.1f}M"
    if tokens >= 1_000:
        return f"{tokens / 1_000:.1f}k"
    return str(tokens)


# Fix 6.3: Use format_goal_list from utils.goals instead of duplicate implementation
def _format_goal_summary(agent: Any) -> str:
    try:
        goals = list(agent.list_goals())
    except Exception:
        goals = []
    return "Goals: " + format_goal_list(goals)


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
    stop_event = threading.Event()
    gui_thread = {"ref": None}

    def _notify(title: str, message: str) -> None:
        try:
            os_layer.send_notification(title, message)
        except Exception:
            pass

    def on_open_gui(_icon, _item):
        if gui_thread["ref"] is not None and gui_thread["ref"].is_alive():
            print("Tray action: GUI already running")
            _notify("NOVA", "GUI is already running.")
            return

        def _launch():
            try:
                from interfaces.gui.app import launch_gui

                launch_gui(agent, notify_fn=_notify)
            except Exception as exc:
                print(f"Tray action: failed to open GUI: {exc}")
                _notify("NOVA GUI Error", f"Failed to launch GUI: {exc}")

        gui_thread["ref"] = threading.Thread(target=_launch, daemon=True)
        gui_thread["ref"].start()
        print("Tray action: opening GUI")

    def on_switch_work(_icon, _item):
        state = agent.switch_session(DEFAULT_SESSION_WORK)
        _notify("NOVA", f"Switched to session: {state.name}")

    def on_switch_personal(_icon, _item):
        state = agent.switch_session(DEFAULT_SESSION_PERSONAL)
        _notify("NOVA", f"Switched to session: {state.name}")

    def on_toggle_mute(_icon, _item):
        muted = bool(agent.toggle_mute())
        _notify("NOVA", "Muted proactive alerts" if muted else "Unmuted proactive alerts")

    def on_health(_icon, _item):
        try:
            _notify("NOVA Health", _format_health_summary(agent))
        except Exception as exc:
            _notify("NOVA Health", f"Health unavailable: {exc}")

    def on_goals(_icon, _item):
        try:
            _notify("NOVA Goals", format_goal_list(agent.list_goals()))
        except Exception as exc:
            _notify("NOVA Goals", f"Goals unavailable: {exc}")

    def on_alerts(_icon, _item):
        try:
            _notify("NOVA Alerts", format_event_log(agent.recent_events()))
        except Exception as exc:
            _notify("NOVA Alerts", f"Alerts unavailable: {exc}")

    def on_export(_icon, _item):
        try:
            path = agent.export_session("md")
            _notify("NOVA", f"Exported session -> {path}")
        except Exception as exc:
            _notify("NOVA", f"Export failed: {exc}")

    def on_quit(icon, _item):
        running["value"] = False
        stop_event.set()
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
            if stop_event.wait(10):
                break

    threading.Thread(target=_keep_title_fresh, daemon=True).start()
    icon.run()
