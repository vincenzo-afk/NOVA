"""OS abstraction helpers."""

from __future__ import annotations

import platform
import shlex
import subprocess
from pathlib import Path


def _run(cmd: list[str], timeout: float = 2.0) -> str:
    try:
        return subprocess.check_output(cmd, text=True, timeout=timeout).strip()
    except Exception:
        return ""


def get_foreground_app() -> str:
    system = platform.system().lower()
    if "darwin" in system:
        app = _run(
            [
                "osascript",
                "-e",
                'tell application "System Events" to get name of first process whose frontmost is true',
            ]
        )
        return app or "unknown"
    if "linux" in system:
        window_id = _run(["bash", "-lc", "xprop -root _NET_ACTIVE_WINDOW 2>/dev/null | awk '{print $5}'"])
        if not window_id:
            window_id = _run(["bash", "-lc", "xdotool getwindowfocus 2>/dev/null"])
        if not window_id:
            return "unknown"
        app = _run(["bash", "-lc", f"xprop -id {shlex.quote(window_id)} WM_CLASS 2>/dev/null"])
        if app:
            return app
        return _run(["bash", "-lc", f"xprop -id {shlex.quote(window_id)} WM_NAME 2>/dev/null"]) or "unknown"
    if "windows" in system:
        try:
            import ctypes

            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            if hwnd:
                buf = ctypes.create_unicode_buffer(512)
                user32.GetWindowTextW(hwnd, buf, 512)
                title = str(buf.value or "").strip()
                if title:
                    return title
        except Exception:
            pass
        app = _run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "(Get-Process | Where-Object {$_.MainWindowHandle -ne 0} | "
                "Sort-Object StartTime -Descending | Select-Object -First 1).ProcessName",
            ],
            timeout=3.0,
        )
        return app or "unknown"
    return "unknown"


def send_notification(title: str, message: str) -> None:
    system = platform.system().lower()
    if "darwin" in system:
        subprocess.run(
            [
                "osascript",
                "-e",
                f'display notification {shlex.quote(message)} with title {shlex.quote(title)}',
            ],
            check=False,
        )
        return
    if "linux" in system:
        if subprocess.run(
            ["sh", "-lc", "command -v notify-send >/dev/null 2>&1"],
            check=False,
        ).returncode == 0:
            subprocess.run(["notify-send", title, message], check=False)
            return
    if "windows" in system:
        try:
            from win10toast import ToastNotifier  # type: ignore[import]

            ToastNotifier().show_toast(str(title), str(message), threaded=True, duration=5)
            return
        except Exception:
            pass
        subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                f"New-BurntToastNotification -Text {shlex.quote(title)}, {shlex.quote(message)}",
            ],
            check=False,
        )
        return
    print(f"[{title}] {message}")


def startup_command(repo_root: str, python_executable: str = "", entrypoint: str = "main.py") -> str:
    python_bin = python_executable.strip() or "python3"
    root = str(Path(repo_root).resolve())
    return f"cd {shlex.quote(root)} && {shlex.quote(python_bin)} {shlex.quote(entrypoint)}"


def register_startup(command: str, app_name: str = "jarvis") -> str:
    system = platform.system().lower()
    clean_command = command.strip()
    if not clean_command:
        raise ValueError("command is required")

    if "darwin" in system:
        launch_agents = Path.home() / "Library" / "LaunchAgents"
        launch_agents.mkdir(parents=True, exist_ok=True)
        plist_path = launch_agents / f"com.{app_name}.agent.plist"
        plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.{app_name}.agent</string>
  <key>ProgramArguments</key><array><string>/bin/bash</string><string>-lc</string><string>{clean_command}</string></array>
  <key>RunAtLoad</key><true/>
</dict>
</plist>"""
        plist_path.write_text(plist, encoding="utf-8")
        subprocess.run(["launchctl", "unload", str(plist_path)], check=False)
        subprocess.run(["launchctl", "load", str(plist_path)], check=False)
        return str(plist_path)

    if "linux" in system:
        systemd_dir = Path.home() / ".config" / "systemd" / "user"
        systemd_dir.mkdir(parents=True, exist_ok=True)
        service_path = systemd_dir / f"{app_name}.service"
        service = f"""[Unit]
Description={app_name.upper()} Agent
After=network.target

[Service]
Type=simple
ExecStart=/bin/bash -lc {shlex.quote(clean_command)}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
"""
        service_path.write_text(service, encoding="utf-8")
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
        subprocess.run(["systemctl", "--user", "enable", "--now", f"{app_name}.service"], check=False)
        return str(service_path)

    if "windows" in system:
        task_name = f"{app_name.capitalize()}Agent"
        subprocess.run(
            [
                "schtasks",
                "/Create",
                "/SC",
                "ONLOGON",
                "/TN",
                task_name,
                "/TR",
                clean_command,
                "/F",
            ],
            check=False,
        )
        return task_name

    raise RuntimeError(f"Unsupported operating system: {system}")
