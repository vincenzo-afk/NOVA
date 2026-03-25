"""ADB command wrapper."""

from __future__ import annotations

from pathlib import Path
import subprocess


class ADBClient:
    def __init__(self, device: str | None = None):
        self.device = device

    def _cmd(self, *parts: str) -> str:
        base = ["adb"]
        if self.device:
            base.extend(["-s", self.device])
        base.extend(parts)
        return subprocess.check_output(base, text=True).strip()

    def connect(self, host: str, port: int = 5555) -> str:
        return self._cmd("connect", f"{host}:{port}")

    def devices(self) -> list[str]:
        out = self._cmd("devices")
        rows = [line.strip() for line in out.splitlines()[1:] if line.strip()]
        return [line.split()[0] for line in rows if "\tdevice" in line]

    def shell(self, command: str) -> str:
        return self._cmd("shell", command)

    def screenshot(self, out_path: str = "/sdcard/jarvis_screen.png") -> str:
        self._cmd("shell", f"screencap -p {out_path}")
        return out_path

    def pull(self, remote_path: str, local_path: str) -> str:
        self._cmd("pull", remote_path, local_path)
        return local_path

    def push(self, local_path: str, remote_path: str) -> str:
        self._cmd("push", local_path, remote_path)
        return remote_path

    def tap(self, x: int, y: int) -> str:
        return self.shell(f"input tap {int(x)} {int(y)}")

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 250) -> str:
        return self.shell(f"input swipe {int(x1)} {int(y1)} {int(x2)} {int(y2)} {int(duration_ms)}")

    def type_text(self, text: str) -> str:
        safe = text.replace(" ", "%s")
        return self.shell(f"input text {safe}")

    def launch_app(self, package_name: str) -> str:
        return self.shell(f"monkey -p {package_name} -c android.intent.category.LAUNCHER 1")

    def keyevent(self, key_code: str | int) -> str:
        return self.shell(f"input keyevent {key_code}")

    def send_sms(self, phone_number: str, body: str) -> str:
        safe_body = body.replace('"', '\\"')
        return self.shell(
            "am start -a android.intent.action.SENDTO "
            f"-d sms:{phone_number} --es sms_body \"{safe_body}\""
        )

    def notifications_dump(self) -> str:
        return self.shell("dumpsys notification")

    def sms_dump(self, limit: int = 20) -> str:
        return self.shell(f"content query --uri content://sms --projection address:body:date --limit {int(limit)}")

    def screenshot_to_local(self, local_path: str = "assets/phone_screen.png") -> str:
        remote = "/sdcard/jarvis_screen.png"
        self.screenshot(remote)
        Path(local_path).parent.mkdir(parents=True, exist_ok=True)
        self.pull(remote, local_path)
        return local_path
