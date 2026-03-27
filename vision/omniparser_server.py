"""OmniParser local process manager."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from urllib.parse import urlparse

import requests


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

    def ensure_running(self) -> None:
        if self.is_running():
            return
        if self.proc and self.proc.poll() is None:
            return
        env = os.environ.copy()
        project_root = Path.cwd().resolve()
        env["PYTHONPATH"] = f"{project_root}{os.pathsep}{env.get('PYTHONPATH', '')}".strip(os.pathsep)
        cwd = str(project_root)
        if self.repo_dir:
            repo_path = Path(self.repo_dir).expanduser().resolve()
            env["PYTHONPATH"] = f"{repo_path}{os.pathsep}{env.get('PYTHONPATH', '')}".strip(os.pathsep)
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)
        log_path = log_dir / "omniparser_server.log"
        self.log_file = log_path.open("a", encoding="utf-8")
        self.proc = subprocess.Popen(
            self.command,
            stdout=self.log_file,
            stderr=self.log_file,
            env=env,
            cwd=cwd,
        )

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
            "python3",
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
