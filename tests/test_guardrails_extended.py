"""Unit tests for guardrails — risk scoring and path-based escalation.

Covers:
- System-path detection escalating writes to high-risk (Security 4.3 fix)
- Registry allowlist blocking (Security fix)
- Emergency stop persistence round-trip
- Sensitive arg scrubbing in logs (Security 1.1 fix)
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from core.tools.dispatcher import ToolCall
from safety.guardrails import Guardrails, _scrub_args


# ---------------------------------------------------------------------------
# _scrub_args — sensitive field masking
# ---------------------------------------------------------------------------

def test_scrub_args_masks_api_key():
    scrubbed = _scrub_args({"api_key": "sk-secret123", "query": "hello"})
    assert scrubbed["api_key"] == "***REDACTED***"
    assert scrubbed["query"] == "hello"


def test_scrub_args_masks_nested():
    scrubbed = _scrub_args({"outer": {"password": "hunter2", "value": "safe"}})
    assert scrubbed["outer"]["password"] == "***REDACTED***"
    assert scrubbed["outer"]["value"] == "safe"


# ---------------------------------------------------------------------------
# check() — system path escalation (Security 4.3)
# ---------------------------------------------------------------------------

def _make_guardrails(**kw) -> Guardrails:
    with tempfile.TemporaryDirectory() as td:
        return Guardrails(log_path=str(Path(td) / "test.jsonl"), **kw)


def test_write_to_system32_is_high_risk():
    g = _make_guardrails()
    call = ToolCall(tool="win32_api.write", args={"path": "C:\\Windows\\System32\\evil.dll", "content": "x"})
    result = g.check(call)
    assert result.level == "high"
    assert result.score >= 7


def test_write_to_normal_path_is_not_high():
    g = _make_guardrails()
    call = ToolCall(tool="win32_api.write", args={"path": "C:\\Users\\user\\notes.txt", "content": "hello"})
    result = g.check(call)
    assert result.level in {"low", "medium"}


def test_registry_write_outside_allowlist_is_blocked():
    g = _make_guardrails()
    call = ToolCall(
        tool="win32_api.registry_write",
        args={"path": "HKLM\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run", "name": "evil", "value": "malware.exe"},
    )
    result = g.check(call)
    assert result.blocked is True
    assert result.reason == "registry_path_not_in_allowlist"


def test_registry_write_inside_allowlist_passes():
    g = _make_guardrails()
    call = ToolCall(
        tool="win32_api.registry_write",
        args={"path": "HKEY_CURRENT_USER\\SOFTWARE\\NOVA\\prefs", "name": "theme", "value": "dark"},
    )
    result = g.check(call)
    assert result.blocked is False


# ---------------------------------------------------------------------------
# Emergency stop persistence (Critical 1.9)
# ---------------------------------------------------------------------------

def test_emergency_stop_persists_and_clears(tmp_path, monkeypatch):
    stop_file = tmp_path / "emergency_stop"
    import safety.guardrails as gm
    monkeypatch.setattr(gm, "_EMERGENCY_STOP_FILE", stop_file)

    g = Guardrails(log_path=str(tmp_path / "test.jsonl"))
    assert not g.is_emergency_stopped()

    g.emergency_stop()
    assert g.is_emergency_stopped()
    assert stop_file.exists()

    g.clear_emergency_stop()
    assert not g.is_emergency_stopped()
    assert not stop_file.exists()


def test_emergency_stop_loaded_on_startup(tmp_path, monkeypatch):
    """A process restarted after emergency_stop() must boot with stop already active."""
    stop_file = tmp_path / "emergency_stop"
    stop_file.write_text("1")
    import safety.guardrails as gm
    monkeypatch.setattr(gm, "_EMERGENCY_STOP_FILE", stop_file)

    g = Guardrails(log_path=str(tmp_path / "test.jsonl"))
    assert g.is_emergency_stopped(), "Stop flag should be loaded from disk on init"
