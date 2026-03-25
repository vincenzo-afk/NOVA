"""OmniParser local process manager."""

from __future__ import annotations

import subprocess

import requests


class OmniParserServer:
    def __init__(self, url: str = "http://localhost:8000", command: list[str] | None = None):
        self.url = url
        self.command = command or ["python3", "-m", "omniparser.server"]
        self.proc: subprocess.Popen | None = None

    def is_running(self) -> bool:
        try:
            response = requests.get(f"{self.url}/health", timeout=2)
            return response.ok
        except Exception:
            return False

    def ensure_running(self) -> None:
        if self.is_running():
            return
        if self.proc and self.proc.poll() is None:
            return
        self.proc = subprocess.Popen(self.command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()

    def restart(self) -> None:
        self.stop()
        self.ensure_running()
