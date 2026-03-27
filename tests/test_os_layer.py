from __future__ import annotations

from pathlib import Path

import control.os_layer as os_layer


def test_startup_command_builds_shell_wrapper(tmp_path):
    command = os_layer.startup_command(str(tmp_path), python_executable="/usr/bin/python3", entrypoint="main.py")
    assert "main.py" in command
    assert "/usr/bin/python3" in command


def test_register_startup_linux_writes_service_file(monkeypatch, tmp_path):
    commands: list[list[str]] = []

    def fake_system() -> str:
        return "Linux"

    def fake_run(cmd, check=False, **kwargs):
        _ = kwargs
        commands.append(list(cmd))
        return None

    monkeypatch.setattr(os_layer.platform, "system", fake_system)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.setattr(os_layer.subprocess, "run", fake_run)

    service_path = os_layer.register_startup("python3 main.py", app_name="jarvis")

    path = Path(service_path)
    assert path.exists()
    content = path.read_text(encoding="utf-8")
    assert "ExecStart=/bin/bash -lc" in content
    assert "python3 main.py" in content
    assert any(cmd[:3] == ["systemctl", "--user", "daemon-reload"] for cmd in commands)
