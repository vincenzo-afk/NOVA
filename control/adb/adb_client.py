"""ADB command wrapper with per-device lock and safe SMS construction.

Fixes applied:
- 1.3: send_sms() now uses ADB arg parser (--es flags) instead of shell-escaped f-strings.
- 5.3: Exposes a per-device lock for callers to prevent concurrent ADB commands.
"""

from __future__ import annotations

import shlex
from pathlib import Path
import subprocess
import threading


class ADBClient:
    def __init__(self, device: str | None = None):
        self.device = device
        # fix 5.3: per-device lock — callers share this to serialize ADB commands
        self._lock = threading.Lock()

    def _cmd(self, *parts: str) -> str:
        base = ["adb"]
        if self.device:
            base.extend(["-s", self.device])
        base.extend(parts)
        with self._lock:
            return subprocess.check_output(base, text=True).strip()  # nosec B603

    def connect(self, host: str, port: int = 5555) -> str:
        return self._cmd("connect", f"{host}:{port}")

    def devices(self) -> list[str]:
        out = self._cmd("devices")
        rows = [line.strip() for line in out.splitlines()[1:] if line.strip()]
        return [line.split()[0] for line in rows if "\tdevice" in line]

    def shell(self, *args: str) -> str:
        """Execute an adb shell command using a proper arg list (no shell=True)."""
        return self._cmd("shell", *args)

    def screenshot(self, out_path: str = "/sdcard/jarvis_screen.png") -> str:
        self.shell("screencap", "-p", out_path)
        return out_path

    def pull(self, remote_path: str, local_path: str) -> str:
        self._cmd("pull", remote_path, local_path)
        return local_path

    def push(self, local_path: str, remote_path: str) -> str:
        self._cmd("push", local_path, remote_path)
        return remote_path

    def tap(self, x: int, y: int) -> str:
        return self.shell("input", "tap", str(int(x)), str(int(y)))

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 250) -> str:
        return self.shell(
            "input", "swipe",
            str(int(x1)), str(int(y1)), str(int(x2)), str(int(y2)), str(int(duration_ms)),
        )

    def type_text(self, text: str) -> str:
        # Use ADB's own escaping for shell-sensitive characters.
        safe = text.replace("\n", " ").replace("\r", " ")
        for ch in ("\\", "&", "|", ";", "<", ">", "(", ")", "$", "`", "\"", "'"):
            safe = safe.replace(ch, f"\\{ch}")
        safe = safe.replace(" ", "%s")
        return self.shell("input", "text", safe)

    def launch_app(self, package_name: str) -> str:
        return self.shell(
            "monkey", "-p", package_name, "-c", "android.intent.category.LAUNCHER", "1"
        )

    def keyevent(self, key_code: str | int) -> str:
        return self.shell("input", "keyevent", str(key_code))

    def send_sms(self, phone_number: str, body: str) -> str:
        """Send SMS via ADB using structured --es arguments.

        Fix 1.3: Previous implementation used an f-string with shell escaping,
        which was vulnerable to injection via backticks, $(), or newlines.
        Now uses ADB's own argument parser through a proper arg list.
        """
        from config.settings import settings
        # Security: fail closed when allowlist is empty.
        if not settings.ALLOWED_PHONE_NUMBERS:
            raise ValueError("ALLOWED_PHONE_NUMBERS is empty; SMS sending is blocked.")
        if phone_number not in settings.ALLOWED_PHONE_NUMBERS:
            raise ValueError(f"Phone number {phone_number} is not in ALLOWED_PHONE_NUMBERS.")
        
        return self.shell(
            "am", "start",
            "-a", "android.intent.action.SENDTO",
            "-d", f"sms:{phone_number}",
            "--es", "sms_body", body,
            "--ez", "exit_on_sent", "true",
        )

    def notifications_dump(self) -> str:
        return self.shell("dumpsys", "notification")

    def sms_dump(self, limit: int = 20) -> str:
        return self.shell(
            "content", "query",
            "--uri", "content://sms",
            "--projection", "address:body:date",
            "--limit", str(int(limit)),
        )

    def screenshot_to_local(self, local_path: str = "assets/phone_screen.png") -> str:
        remote = "/sdcard/jarvis_screen.png"
        self.screenshot(remote)
        Path(local_path).parent.mkdir(parents=True, exist_ok=True)
        self.pull(remote, local_path)
        return local_path
