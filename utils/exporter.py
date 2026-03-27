"""Exports session history to JSON or Markdown files."""

from __future__ import annotations

import json
from pathlib import Path


def export_json(history: list[dict], path: str) -> str:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(history, indent=2, ensure_ascii=False), encoding="utf-8")
    return str(out)


def export_markdown(history: list[dict], path: str) -> str:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# JARVIS Session Export", ""]
    for turn in history:
        role = turn.get("role", "unknown").title()
        content = turn.get("content", "")
        lines.append(f"## {role}")
        lines.append(content)
        lines.append("")
    out.write_text("\n".join(lines), encoding="utf-8")
    return str(out)
