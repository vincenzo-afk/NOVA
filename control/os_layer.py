"""OS abstraction helpers."""

from __future__ import annotations

import platform
import subprocess
from pathlib import Path


def get_foreground_app() -> str:
    system = platform.system().lower()
    if "darwin" in system:
        try:
            return subprocess.check_output(
                [
                    "osascript",
                    "-e",
                    'tell application "System Events" to get name of first process whose frontmost is true',
                ],
                text=True,
                timeout=1.0,
            ).strip()
        except Exception:
            return "unknown"
    return "unknown"


def send_notification(title: str, message: str) -> None:
    system = platform.system().lower()
    if "darwin" in system:
        subprocess.run(
            [
                "osascript",
                "-e",
                f'display notification "{message}" with title "{title}"',
            ],
            check=False,
        )
    else:
        print(f"[{title}] {message}")


def register_startup(command: str) -> None:
    system = platform.system().lower()
    if "darwin" in system:
        launch_agents = Path.home() / "Library" / "LaunchAgents"
        launch_agents.mkdir(parents=True, exist_ok=True)
        plist_path = launch_agents / "com.jarvis.agent.plist"
        plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.jarvis.agent</string>
  <key>ProgramArguments</key><array><string>/bin/bash</string><string>-lc</string><string>{command}</string></array>
  <key>RunAtLoad</key><true/>
</dict>
</plist>"""
        plist_path.write_text(plist, encoding="utf-8")
        subprocess.run(["launchctl", "load", str(plist_path)], check=False)
