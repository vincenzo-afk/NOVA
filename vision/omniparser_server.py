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
import threading
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


def _is_safe_pythonpath_entry(entry: str) -> bool:
    try:
        resolved = Path(entry).expanduser().resolve()
    except Exception:
        return False
    if not resolved.exists():
        return False
    safe_roots = [
        Path.cwd().resolve(),
        Path.home().resolve(),
        Path(sys.prefix).resolve(),
        Path(getattr(sys, "base_prefix", sys.prefix)).resolve(),
    ]
    return any(str(resolved).startswith(str(root)) for root in safe_roots)


def _safe_env(extra_pythonpath: str = "", auth_token: str = "") -> dict[str, str]:
    """Build a minimal environment for the OmniParser subprocess.

    Only passes PATH, PYTHONPATH, and HOME — never any API keys or tokens.
    """
    safe: dict[str, str] = {}
    for key in (
        "PATH",
        "HOME",
        "XDG_CACHE_HOME",
        "TMPDIR",
        "TEMP",
        "TMP",
        "SYSTEMROOT",
        "COMSPEC",
        "USERPROFILE",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
    ):
        val = os.environ.get(key)
        if val:
            safe[key] = val

    pythonpath_parts: list[str] = []
    for source in (extra_pythonpath, os.environ.get("PYTHONPATH", "")):
        if not source:
            continue
        for raw in source.split(os.pathsep):
            value = raw.strip()
            if not value:
                continue
            if _is_safe_pythonpath_entry(value) and value not in pythonpath_parts:
                pythonpath_parts.append(value)
    if pythonpath_parts:
        safe["PYTHONPATH"] = os.pathsep.join(pythonpath_parts)
    if auth_token:
        safe["OMNIPARSER_AUTH_TOKEN"] = auth_token
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
        self._proc_lock = threading.Lock()
        # Fix 7.3: Generate random auth token for API security
        self.auth_token = secrets.token_urlsafe(32)
        if not self.command:
            self.command = self._build_default_command()

    def is_running(self) -> bool:
        token_q = f"?token={self.auth_token}" if self.auth_token else ""
        for path in ("/health", "/probe", "/probe/"):
            try:
                response = requests.get(f"{self.url}{path}{token_q}", timeout=2)
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
        with self._proc_lock:
            if self.proc is not None and self.proc.poll() is not None and not self.is_running():
                try:
                    print(f"[omniparser] previous process exited with code {self.proc.returncode}; restarting")
                except Exception:
                    pass
                self.proc = None

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

                env = _safe_env(extra_pythonpath=pythonpath, auth_token=self.auth_token)
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
            wait = min(delay * (2 ** (attempt - 1)), 4.0)
            print(f"[omniparser] waiting for server startup (attempt {attempt}, sleeping {wait:.0f}s)…")
            time.sleep(wait)

        print("[omniparser] server did not become healthy within startup timeout — killing and continuing anyway")
        with self._proc_lock:
            if self.proc:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
                self.proc = None

    def stop(self) -> None:
        with self._proc_lock:
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
        self.auth_token = secrets.token_urlsafe(32)
        self.command = self._build_default_command()
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
        ]
        if repo_path:
            command += ["--repo-dir", str(repo_path)]
        if som_path:
            command += ["--som-model-path", str(som_path)]
        if caption_path:
            command += ["--caption-model-path", str(caption_path)]
        return command
