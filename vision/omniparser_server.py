"""OmniParser local process manager.

Fixes applied:
- 1.4: Strip all secrets from subprocess environment — only PATH and PYTHONPATH passed.
- 2.11: Poll is_running() with exponential backoff after Popen to wait for startup.
"""

from __future__ import annotations

import os
import secrets
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import requests


_SECRET_ENV_PREFIXES = (
    "OPENAI_",
    "GEMINI_",
    "MEM0_",
    "TELEGRAM_",
    "PORCUPINE_",
    "ANTHROPIC_",
    "GOOGLE_",
    "AWS_",
)


def _safe_env(extra_pythonpath: str = "") -> dict[str, str]:
    """Build a minimal environment for the OmniParser subprocess.

    Only passes PATH, PYTHONPATH, and HOME — never any API keys or tokens.
    """
    safe: dict[str, str] = {}
    for key in ("PATH", "HOME", "TMPDIR", "TEMP", "TMP", "SYSTEMROOT", "USERPROFILE"):
        val = os.environ.get(key)
        if val:
            safe[key] = val

    pythonpath_parts = [p for p in [extra_pythonpath, os.environ.get("PYTHONPATH", "")] if p]
    if pythonpath_parts:
        safe["PYTHONPATH"] = os.pathsep.join(pythonpath_parts)
    return safe


class OmniParserServer:
    def __init__(
        self,
        url: str = "http://localhost:8000",
        command: list[str] | None = None,
        repo_dir: str | None = None,
    ):
        self.url = url
        self.command = command or []
        self.repo_dir = repo_dir or os.getenv("OMNIPARSER_REPO_DIR", "")
        self.proc: subprocess.Popen | None = None
        self.log_file = None
        # Fix 7.3: Generate random auth token for API security
        self.auth_token = secrets.token_urlsafe(32)
        if not self.command:
            self.command = self._build_default_command()

    def is_running(self) -> bool:
        for path in ("/health", "/probe", "/probe/"):
            try:
                response = requests.get(f"{self.url}{path}", timeout=2)
                if response.ok:
                    return True
            except Exception:
                continue
        return False

    def ensure_running(self, startup_timeout: float = 120.0) -> None:
        """Start OmniParser server if not running, then wait for it to become healthy.

        Fix 2.11: polls with exponential backoff for up to `startup_timeout` seconds.
        Fix 1.4: passes only a safe, secret-free environment to the subprocess.
        """
        if self.is_running():
            return
        if self.proc and self.proc.poll() is None:
            # Process is alive but not responding yet — wait below
            pass
        else:
            project_root = Path.cwd().resolve()
            pythonpath = str(project_root)
            if self.repo_dir:
                pythonpath = str(Path(self.repo_dir).expanduser().resolve()) + os.pathsep + pythonpath

            env = _safe_env(extra_pythonpath=pythonpath)
            log_dir = Path("logs")
            log_dir.mkdir(exist_ok=True)
            log_path = log_dir / "omniparser_server.log"
            if self.log_file:
                try:
                    self.log_file.close()
                except Exception:
                    pass
            self.log_file = log_path.open("a", encoding="utf-8")
            self.proc = subprocess.Popen(
                self.command,
                stdout=self.log_file,
                stderr=self.log_file,
                env=env,
                cwd=str(project_root),
            )

        # Poll with exponential backoff up to startup_timeout
        delay = 1.0
        deadline = time.monotonic() + startup_timeout
        attempt = 0
        while time.monotonic() < deadline:
            if self.is_running():
                return
            attempt += 1
            wait = min(delay * (2 ** (attempt - 1)), 16.0)
            print(f"[omniparser] waiting for server startup (attempt {attempt}, sleeping {wait:.0f}s)…")
            time.sleep(wait)

        print("[omniparser] server did not become healthy within startup timeout — killing and continuing anyway")
        if self.proc:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
        if self.log_file:
            try:
                self.log_file.close()
            except Exception:
                pass
            self.log_file = None

    def restart(self) -> None:
        self.stop()
        self.ensure_running()

    def _build_default_command(self) -> list[str]:
        parsed = urlparse(self.url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 8000
        repo_path = Path(self.repo_dir).expanduser().resolve() if self.repo_dir else None
        weights_dir = repo_path / "weights" if repo_path else None
        som_path = weights_dir / "icon_detect" / "model.pt" if weights_dir else None
        caption_path = weights_dir / "icon_caption_florence" if weights_dir else None
        command = [
            sys.executable,
            "-m",
            "vision.omniparser_app",
            "--host",
            host,
            "--port",
            str(port),
            "--auth-token",
            self.auth_token,
        ]
        if repo_path:
            command += ["--repo-dir", str(repo_path)]
        if som_path:
            command += ["--som-model-path", str(som_path)]
        if caption_path:
            command += ["--caption-model-path", str(caption_path)]
        return command
