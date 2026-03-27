"""Notification helpers for autonomy and background events."""

from __future__ import annotations

from typing import Any, Callable

import requests


def send_telegram_text(
    bot_token: str,
    chat_id: str,
    text: str,
    timeout_seconds: int = 12,
) -> dict[str, Any]:
    token = bot_token.strip()
    target_chat = chat_id.strip()
    if not token or not target_chat:
        return {"ok": False, "error": "missing_bot_token_or_chat_id"}

    try:
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": target_chat, "text": text},
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict):
            return payload
        return {"ok": False, "error": "invalid_telegram_response"}
    except Exception as exc:
        return {"ok": False, "error": f"telegram_send_failed: {exc}"}


def build_goal_status_message(
    goal_id: str,
    goal: str,
    status: str,
    reason: str,
    next_index: int,
    total_steps: int,
) -> str:
    head = f"Autonomy goal {goal_id} ({goal}) {status}."
    progress = f"Progress: step {next_index}/{total_steps}."
    reason_text = f"Reason: {reason}." if reason else ""

    if status == "paused" and "max_steps" in reason:
        action = f"Resume with goal.resume using goal_id={goal_id}."
        return " ".join(part for part in [head, progress, reason_text, action] if part).strip()

    return " ".join(part for part in [head, progress, reason_text] if part).strip()


def notify_background_event(
    message: str,
    *,
    muted: bool,
    notify_telegram: Callable[[str], Any] | None = None,
    notify_tts: Callable[[str], Any] | None = None,
) -> dict[str, bool]:
    if muted:
        return {"telegram": False, "tts": False}

    telegram_sent = False
    tts_sent = False
    if notify_telegram is not None:
        try:
            telegram_sent = bool(notify_telegram(message))
        except Exception:
            telegram_sent = False
    if notify_tts is not None:
        try:
            tts_sent = bool(notify_tts(message))
        except Exception:
            tts_sent = False
    return {"telegram": telegram_sent, "tts": tts_sent}
