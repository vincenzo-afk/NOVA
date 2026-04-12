"""Settings persistence and profile manager.

Provides load/save, profile switching, and live mutation of settings values
without restarting the process. Changes are written to a JSONL overlay file
rather than mutating .env so the original env file is always preserved.
"""

from __future__ import annotations

import json
import os
import shutil
import threading
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config.settings import settings, Settings


_OVERLAY_FILE = Path(".jarvis/settings_overlay.json")
_PROFILES_DIR = Path(".jarvis/settings_profiles")
_SCHEMA_FILE = Path(__file__).parent / "settings_schema.json"
_LOCK = threading.Lock()

# ── Sentinel so callers can detect no-value without None ambiguity ──────────
_MISSING = object()


# ---------------------------------------------------------------------------
# Schema helpers
# ---------------------------------------------------------------------------

def load_schema() -> dict:
    """Return the parsed settings_schema.json, cached after first load."""
    if not hasattr(load_schema, "_cache"):
        try:
            load_schema._cache = json.loads(_SCHEMA_FILE.read_text(encoding="utf-8"))
        except Exception:
            load_schema._cache = {"version": 1, "groups": []}
    return load_schema._cache


def schema_flat() -> dict[str, dict]:
    """Return schema fields keyed by setting name."""
    flat = {}
    for group in load_schema().get("groups", []):
        for s in group.get("settings", []):
            flat[s["key"]] = s
    return flat


def schema_groups() -> list[dict]:
    """Return the ordered setting groups with their field defs."""
    return load_schema().get("groups", [])


# ---------------------------------------------------------------------------
# Overlay persistence
# ---------------------------------------------------------------------------

def _load_overlay() -> dict[str, Any]:
    """Read persisted runtime overrides. Returns {} on any error."""
    try:
        if _OVERLAY_FILE.exists():
            return json.loads(_OVERLAY_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_overlay(data: dict[str, Any]) -> None:
    """Atomically persist the overlay dict."""
    _OVERLAY_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _OVERLAY_FILE.with_suffix(".json.tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(_OVERLAY_FILE)
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        raise


# ---------------------------------------------------------------------------
# Live setting mutation
# ---------------------------------------------------------------------------

def _coerce_value(key: str, raw: Any) -> Any:
    """Coerce raw value to the type declared in the schema."""
    flat = schema_flat()
    spec = flat.get(key)
    if spec is None:
        return raw
    t = spec.get("type", "str")
    try:
        if t == "bool":
            if isinstance(raw, bool):
                return raw
            return str(raw).strip().lower() in {"1", "true", "yes", "y", "on"}
        if t == "int":
            return int(raw)
        if t == "float":
            return float(raw)
        if t == "csv":
            if isinstance(raw, list):
                return raw
            return [v.strip() for v in str(raw).split(",") if v.strip()]
        return str(raw)
    except (ValueError, TypeError):
        return raw


def apply_setting(key: str, value: Any) -> str:
    """
    Set *key* to *value* on the live settings object **and** persist to
    the overlay file. Returns a status message string.
    """
    coerced = _coerce_value(key, value)
    with _LOCK:
        if not hasattr(settings, key):
            return f"Unknown setting: {key}"
        setattr(settings, key, coerced)
        overlay = _load_overlay()
        overlay[key] = coerced
        try:
            _save_overlay(overlay)
        except Exception as exc:
            return f"Setting applied in-memory but failed to persist: {exc}"
    return f"OK: {key} = {coerced!r}"


def get_setting(key: str, default: Any = _MISSING) -> Any:
    """Return the current live value of a setting."""
    with _LOCK:
        val = getattr(settings, key, _MISSING)
    if val is _MISSING:
        if default is _MISSING:
            raise KeyError(f"Unknown setting: {key}")
        return default
    return val


def reset_setting(key: str) -> str:
    """Remove a key from the overlay (revert to env/default on next restart)."""
    with _LOCK:
        overlay = _load_overlay()
        if key in overlay:
            del overlay[key]
            _save_overlay(overlay)
            return f"Removed overlay for {key} — effective after restart"
        return f"{key} has no overlay (using env/default already)"


def apply_overlay_on_boot() -> int:
    """
    Called at startup to replay any persisted overlay onto the live settings
    object. Returns the number of keys applied.
    """
    applied = 0
    overlay = _load_overlay()
    for key, val in overlay.items():
        if hasattr(settings, key):
            try:
                setattr(settings, key, _coerce_value(key, val))
                applied += 1
            except Exception:
                pass
    return applied


# ---------------------------------------------------------------------------
# Profile management
# ---------------------------------------------------------------------------

def list_profiles() -> list[str]:
    """Return names of saved profiles (alphabetical)."""
    _PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    return sorted(p.stem for p in _PROFILES_DIR.glob("*.json"))


def save_profile(name: str) -> str:
    """Snapshot the current overlay as a named profile."""
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name).strip("_")
    if not safe:
        return "Invalid profile name"
    _PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    profile_path = _PROFILES_DIR / f"{safe}.json"
    data = {
        "name": safe,
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "settings": _load_overlay(),
    }
    profile_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return f"Profile '{safe}' saved with {len(data['settings'])} overrides"


def load_profile(name: str) -> str:
    """Apply a saved profile's overrides to the live settings."""
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name).strip("_")
    profile_path = _PROFILES_DIR / f"{safe}.json"
    if not profile_path.exists():
        return f"Profile '{safe}' not found"
    try:
        data = json.loads(profile_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return f"Failed to read profile: {exc}"
    applied = 0
    messages = []
    for key, val in data.get("settings", {}).items():
        result = apply_setting(key, val)
        applied += 1
        messages.append(result)
    return f"Profile '{safe}' loaded: {applied} settings applied"


def delete_profile(name: str) -> str:
    """Delete a named profile file."""
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name).strip("_")
    profile_path = _PROFILES_DIR / f"{safe}.json"
    if not profile_path.exists():
        return f"Profile '{safe}' not found"
    profile_path.unlink(missing_ok=True)
    return f"Profile '{safe}' deleted"


# ---------------------------------------------------------------------------
# Export current settings as .env snippet
# ---------------------------------------------------------------------------

def export_env_snippet(include_secrets: bool = False) -> str:
    """Return an .env-formatted string of all non-default settings."""
    flat = schema_flat()
    overlay = _load_overlay()
    lines = [f"# NOVA settings export — {datetime.now(timezone.utc).isoformat()}"]
    for key, val in overlay.items():
        spec = flat.get(key, {})
        if spec.get("secret") and not include_secrets:
            val = "***REDACTED***"
        if isinstance(val, list):
            val = ",".join(str(v) for v in val)
        lines.append(f"{key}={val}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Full settings dump (for debug/UI display)
# ---------------------------------------------------------------------------

def settings_snapshot(redact_secrets: bool = True) -> dict[str, Any]:
    """Return all live settings values, grouped and optionally redacted."""
    flat = schema_flat()
    result: dict[str, Any] = {}
    with _LOCK:
        raw = asdict(settings)  # type: ignore[call-overload]
    for key, val in raw.items():
        spec = flat.get(key, {})
        if spec.get("secret") and redact_secrets:
            val = "***REDACTED***"
        result[key] = val
    return result
