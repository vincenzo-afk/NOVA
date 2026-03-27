from __future__ import annotations

from pathlib import Path

import setup


def test_startup_command_uses_repo_root(tmp_path):
    command = setup.startup_command(str(tmp_path), python_executable="/usr/bin/python3", entrypoint="main.py")
    assert str(tmp_path.resolve()) in command
    assert "main.py" in command
    assert "/usr/bin/python3" in command


def test_load_env_values_reads_key_value_pairs(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "OPENAI_API_KEYS=a,b\n# comment\nOLLAMA_MODEL=llama3\n",
        encoding="utf-8",
    )
    values = setup.load_env_values(env_path)
    assert values["OPENAI_API_KEYS"] == "a,b"
    assert values["OLLAMA_MODEL"] == "llama3"


def test_verify_wakeword_asset_reports_missing(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(setup, "REPO_ROOT", tmp_path)
    setup.verify_wakeword_asset({"PORCUPINE_KEYWORD_PATH": "./assets/missing.ppn"})
    out = capsys.readouterr().out
    assert "Wake word setup required" in out


def test_maybe_install_ollama_model_pulls_default_model(monkeypatch):
    calls: list[list[str]] = []

    monkeypatch.setattr(setup.shutil, "which", lambda name: "/usr/bin/ollama" if name == "ollama" else None)
    monkeypatch.setattr(setup.subprocess, "run", lambda *args, **kwargs: None)
    monkeypatch.setattr(setup, "run", lambda cmd: calls.append(cmd))

    setup.maybe_install_ollama_model({"OLLAMA_MODEL": "llama3", "OLLAMA_BASE_URL": "http://localhost:11434"})

    assert ["ollama", "pull", "llama3"] in calls


def test_maybe_install_ollama_model_handles_missing_cli(monkeypatch, capsys):
    monkeypatch.setattr(setup.shutil, "which", lambda name: None)
    setup.maybe_install_ollama_model({"OLLAMA_MODEL": "llama3"})
    out = capsys.readouterr().out
    assert "Ollama CLI not found" in out


def test_maybe_install_ollama_model_defaults_when_env_value_blank(monkeypatch):
    calls: list[list[str]] = []

    monkeypatch.setattr(setup.shutil, "which", lambda name: "/usr/bin/ollama" if name == "ollama" else None)
    monkeypatch.setattr(setup.subprocess, "run", lambda *args, **kwargs: None)
    monkeypatch.setattr(setup, "run", lambda cmd: calls.append(cmd))

    setup.maybe_install_ollama_model({"OLLAMA_MODEL": "", "OLLAMA_BASE_URL": "http://localhost:11434"})

    assert ["ollama", "pull", "llama3"] in calls
