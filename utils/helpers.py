"""Shared utility helpers."""

from __future__ import annotations

import json


def pretty_json(value: object) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False)
