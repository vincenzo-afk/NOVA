"""Exports session history to JSON or Markdown files."""

from __future__ import annotations

import json
import re
from pathlib import Path

# Fix 4.1: Redact sensitive fields from session history before export
_SENSITIVE_PATTERNS = [
    (re.compile(r'"api_key"\s*:\s*"[^"\\]*(?:\\.[^"\\]*)*"', re.IGNORECASE | re.DOTALL), '"api_key": "***REDACTED***"'),
    (re.compile(r'"token"\s*:\s*"[^"\\]*(?:\\.[^"\\]*)*"', re.IGNORECASE | re.DOTALL), '"token": "***REDACTED***"'),
    (re.compile(r'"password"\s*:\s*"[^"\\]*(?:\\.[^"\\]*)*"', re.IGNORECASE | re.DOTALL), '"password": "***REDACTED***"'),
    (re.compile(r'"secret"\s*:\s*"[^"\\]*(?:\\.[^"\\]*)*"', re.IGNORECASE | re.DOTALL), '"secret": "***REDACTED***"'),
    (re.compile(r'"access_key"\s*:\s*"[^"\\]*(?:\\.[^"\\]*)*"', re.IGNORECASE | re.DOTALL), '"access_key": "***REDACTED***"'),
    (re.compile(r'"auth_token"\s*:\s*"[^"\\]*(?:\\.[^"\\]*)*"', re.IGNORECASE | re.DOTALL), '"auth_token": "***REDACTED***"'),
]


def _redact_sensitive_data(text: str) -> str:
    """Redact sensitive fields from text before export (fix 4.1)."""
    result = text
    for pattern, replacement in _SENSITIVE_PATTERNS:
        result = pattern.sub(replacement, result)
    return result


def export_json(history: list[dict], path: str) -> str:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    # Fix 4.1: Redact sensitive data before export
    redacted_history = []
    for turn in history:
        redacted_turn = turn.copy()
        if "content" in redacted_turn:
            redacted_turn["content"] = _redact_sensitive_data(str(redacted_turn["content"]))
        redacted_history.append(redacted_turn)
    out.write_text(json.dumps(redacted_history, indent=2, ensure_ascii=False), encoding="utf-8")
    return str(out)


def export_markdown(history: list[dict], path: str) -> str:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# NOVA Session Export", ""]
    for turn in history:
        role = turn.get("role", "unknown").title()
        content = turn.get("content", "")
        # Fix 4.1: Redact sensitive data before export
        redacted_content = _redact_sensitive_data(content)
        lines.append(f"## {role}")
        lines.append(redacted_content)
        lines.append("")
    out.write_text("\n".join(lines), encoding="utf-8")
    return str(out)
