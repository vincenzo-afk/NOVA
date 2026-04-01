"""Multi-Channel Presence Manager — Proactive Intelligence Tier 4.

Routes NOVA notifications to all connected channels based on urgency level.
Replaces direct _notify_telegram() calls throughout NOVAApp.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Any, Callable

log = logging.getLogger(__name__)


class PresenceManager:
    """Routes notifications across Telegram, Slack, and event log based on urgency."""

    # urgency levels
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

    def __init__(
        self,
        telegram_fn: Callable[[str], None] | None = None,
        mcp_call_fn: Callable[[str, str, dict], Any] | None = None,
        record_event_fn: Callable[[str, str], None] | None = None,
        muted_fn: Callable[[], bool] | None = None,
    ):
        """
        Args:
            telegram_fn: fn(message) → send Telegram message
            mcp_call_fn: fn(service, tool_name, args) → call MCP tool
            record_event_fn: fn(kind, message) → log internal event
            muted_fn: fn() → bool; returns True if NOVA is muted
        """
        self._telegram = telegram_fn
        self._mcp_call = mcp_call_fn
        self._record_event = record_event_fn
        self._muted_fn = muted_fn or (lambda: False)

        # Per-channel rate limiting: max 1 message per 10s per channel
        self._rate_limit_window = 10.0
        self._channel_last_send: dict[str, float] = {}
        self._lock = threading.Lock()

    @property
    def _connected_services(self) -> list[str]:
        """Override or inject at runtime via NOVAApp."""
        return []

    def _rate_ok(self, channel: str) -> bool:
        now = time.monotonic()
        with self._lock:
            last = self._channel_last_send.get(channel, 0.0)
            if now - last >= self._rate_limit_window:
                self._channel_last_send[channel] = now
                return True
        return False

    def broadcast(
        self,
        message: str,
        urgency: str = MEDIUM,
        slack_channel: str = "nova-alerts",
        services: list[str] | None = None,
    ) -> dict[str, bool]:
        """
        Route message based on urgency:
          high   → all available channels
          medium → Telegram only
          low    → internal event log only
        """
        if self._muted_fn() and urgency != self.HIGH:
            if self._record_event:
                self._record_event("muted_notification", message[:200])
            return {"muted": True}

        sent: dict[str, bool] = {}

        # Always log internally
        if self._record_event:
            try:
                self._record_event("notification", message[:300])
                sent["event_log"] = True
            except Exception:
                sent["event_log"] = False

        if urgency == self.LOW:
            return sent

        # Telegram — medium + high
        if self._telegram and self._rate_ok("telegram"):
            try:
                self._telegram(message)
                sent["telegram"] = True
            except Exception as exc:
                log.warning("[presence] Telegram send failed: %s", exc)
                sent["telegram"] = False

        if urgency != self.HIGH:
            return sent

        # High urgency: also broadcast to Slack if connected
        available = services or []
        if "slack" in available and self._mcp_call and self._rate_ok("slack"):
            try:
                self._mcp_call("slack", "post_message", {"channel": slack_channel, "text": message})
                sent["slack"] = True
            except Exception as exc:
                log.warning("[presence] Slack send failed: %s", exc)
                sent["slack"] = False

        return sent

    def pr_comment(self, service: str, owner: str, repo: str, pr_number: int, body: str) -> bool:
        """Post a PR comment via GitHub MCP if connected."""
        if not self._mcp_call:
            return False
        try:
            self._mcp_call(
                "github",
                "add_pr_comment",
                {"owner": owner, "repo": repo, "pull_number": pr_number, "body": body},
            )
            return True
        except Exception as exc:
            log.warning("[presence] GitHub PR comment failed: %s", exc)
            return False
