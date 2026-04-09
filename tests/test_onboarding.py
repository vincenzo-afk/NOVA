from __future__ import annotations

from pathlib import Path

import interfaces.onboarding as onboarding


def _read_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        k, v = text.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def test_apply_onboarding_config_text_mode_disables_voice(monkeypatch, tmp_path):
    env_example = tmp_path / ".env.example"
    env_file = tmp_path / ".env"
    soul_file = tmp_path / "SOUL.md"
    flag_file = tmp_path / "config/onboarding_complete"
    profile_file = tmp_path / "config/pc_profile.json"
    env_example.write_text("DEFAULT_LANG=en\nWHISPER_MODEL=base\n", encoding="utf-8")

    monkeypatch.setattr(onboarding, "_ENV_EXAMPLE_PATH", env_example)
    monkeypatch.setattr(onboarding, "_ENV_PATH", env_file)
    monkeypatch.setattr(onboarding, "_SOUL_PATH", soul_file)
    monkeypatch.setattr(onboarding, "_FLAG_PATH", flag_file)
    monkeypatch.setattr(onboarding, "_PROFILE_PATH", profile_file)

    onboarding._apply_onboarding_config(
        {
            "name": "Alex",
            "context": "Engineer",
            "timezone": "UTC+5:30",
            "talk_mode": "text",
            "language": "English",
            "privacy_mode": "balanced",
            "apps": [],
        }
    )

    env = _read_env(env_file)
    assert env["NOVA_VOICE_MODE"] == "text"
    assert env["VOICE_BARGEIN_ENABLED"] == "false"
    assert env["AMBIENT_MONITOR_ENABLED"] == "false"


def test_apply_onboarding_config_always_on_enables_ambient(monkeypatch, tmp_path):
    env_example = tmp_path / ".env.example"
    env_file = tmp_path / ".env"
    soul_file = tmp_path / "SOUL.md"
    flag_file = tmp_path / "config/onboarding_complete"
    profile_file = tmp_path / "config/pc_profile.json"
    env_example.write_text("DEFAULT_LANG=en\nWHISPER_MODEL=base\n", encoding="utf-8")

    monkeypatch.setattr(onboarding, "_ENV_EXAMPLE_PATH", env_example)
    monkeypatch.setattr(onboarding, "_ENV_PATH", env_file)
    monkeypatch.setattr(onboarding, "_SOUL_PATH", soul_file)
    monkeypatch.setattr(onboarding, "_FLAG_PATH", flag_file)
    monkeypatch.setattr(onboarding, "_PROFILE_PATH", profile_file)

    onboarding._apply_onboarding_config(
        {
            "name": "Alex",
            "context": "Engineer",
            "timezone": "UTC+5:30",
            "talk_mode": "voice always-on",
            "language": "Tamil",
            "privacy_mode": "full_cloud",
            "apps": [],
        }
    )

    env = _read_env(env_file)
    assert env["NOVA_VOICE_MODE"] == "always_on"
    assert env["VOICE_BARGEIN_ENABLED"] == "true"
    assert env["AMBIENT_MONITOR_ENABLED"] == "true"
    assert env["DEFAULT_LANG"] == "ta"


def test_apply_onboarding_config_normalizes_invalid_modes(monkeypatch, tmp_path):
    env_example = tmp_path / ".env.example"
    env_file = tmp_path / ".env"
    soul_file = tmp_path / "SOUL.md"
    flag_file = tmp_path / "config/onboarding_complete"
    profile_file = tmp_path / "config/pc_profile.json"
    env_example.write_text("DEFAULT_LANG=en\nWHISPER_MODEL=base\n", encoding="utf-8")

    monkeypatch.setattr(onboarding, "_ENV_EXAMPLE_PATH", env_example)
    monkeypatch.setattr(onboarding, "_ENV_PATH", env_file)
    monkeypatch.setattr(onboarding, "_SOUL_PATH", soul_file)
    monkeypatch.setattr(onboarding, "_FLAG_PATH", flag_file)
    monkeypatch.setattr(onboarding, "_PROFILE_PATH", profile_file)

    onboarding._apply_onboarding_config(
        {
            "name": "Alex",
            "context": "Engineer",
            "timezone": "",
            "talk_mode": "???",
            "language": "English",
            "privacy_mode": "unknown_mode",
            "apps": [],
        }
    )

    env = _read_env(env_file)
    assert env["NOVA_VOICE_MODE"] == "text"
    assert env["PRIVACY_MODE"] == "full_cloud"
