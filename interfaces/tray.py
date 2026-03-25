"""System tray app (minimal controls)."""

from __future__ import annotations

import threading
from typing import Any


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

    def _title() -> str:
        state = "Online" if agent.memory.online else "Offline"
        session = getattr(agent.session.current, "name", "unknown")
        return f"JARVIS • {state} • {session} • {agent.last_provider_label()}"

    def on_status(_icon, _item):
        print(agent.status_text())

    def on_reset(_icon, _item):
        agent.reset_context()
        print("Tray action: context reset")

    def on_work(_icon, _item):
        state = agent.switch_session("jarvis_work")
        print(f"Tray action: switched to {state.name}")

    def on_personal(_icon, _item):
        state = agent.switch_session("jarvis_personal")
        print(f"Tray action: switched to {state.name}")

    def on_quit(icon, _item):
        running["value"] = False
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("Status", on_status),
        pystray.MenuItem("Reset Context", on_reset),
        pystray.MenuItem("Switch: Work", on_work),
        pystray.MenuItem("Switch: Personal", on_personal),
        pystray.MenuItem("Quit", on_quit),
    )
    icon = pystray.Icon("jarvis", icon_image, _title(), menu)

    def _keep_title_fresh():
        while running["value"]:
            icon.title = _title()
            threading.Event().wait(10)

    threading.Thread(target=_keep_title_fresh, daemon=True).start()
    icon.run()
