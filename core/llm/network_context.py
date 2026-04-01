"""Network Context Detector — Proactive Intelligence Tier 1.

Extends NetworkState to detect whether the machine is on a work network,
home network, or unknown. Drives automatic session switching.
"""
from __future__ import annotations

import os
import socket
import threading
import time
from typing import Callable


_DEFAULT_WORK_DOMAINS: list[str] = []
_DETECT_INTERVAL = 300.0  # 5 minutes


def _load_work_domains() -> list[str]:
    raw = os.environ.get("WORK_NETWORK_DOMAINS", "")
    return [d.strip().lower() for d in raw.split(",") if d.strip()]


def _detect_network_context(work_domains: list[str] | None = None) -> str:
    """Return 'work', 'home', or 'unknown' based on DNS suffix and hostname."""
    domains = work_domains if work_domains is not None else _load_work_domains()
    try:
        fqdn = socket.getfqdn().lower()
    except Exception:
        fqdn = ""

    if domains:
        for domain in domains:
            if domain and domain in fqdn:
                return "work"
        # If we have work domains configured but none matched, it's home
        return "home"

    # No domains configured — fall back to hostname heuristic
    try:
        hostname = socket.gethostname().lower()
    except Exception:
        hostname = ""

    if any(kw in hostname for kw in ("work", "corp", "office", "vpn", "enterprise")):
        return "work"
    if any(kw in hostname for kw in ("home", "personal", "local", "macbook", "desktop")):
        return "home"

    return "unknown"


class NetworkContextDetector:
    """Polls network context every 5 minutes and calls back on state change."""

    def __init__(
        self,
        on_change: Callable[[str, str], None] | None = None,
        work_domains: list[str] | None = None,
        interval: float = _DETECT_INTERVAL,
    ):
        """
        Args:
            on_change: fn(old_context, new_context) called when context changes.
            work_domains: list of domain suffixes that identify a work network.
            interval: polling interval in seconds.
        """
        self._on_change = on_change
        self._work_domains = work_domains or _load_work_domains()
        self._interval = max(30.0, interval)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._current_context: str = "unknown"
        self._lock = threading.Lock()

    @property
    def current_context(self) -> str:
        with self._lock:
            return self._current_context

    def detect_once(self) -> str:
        """Run a single network context detection and return the result."""
        return _detect_network_context(self._work_domains)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        # Do an immediate first detection
        ctx = self.detect_once()
        with self._lock:
            self._current_context = ctx
        self._thread = threading.Thread(target=self._loop, daemon=True, name="network-context-detector")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._stop.wait(self._interval)
            if self._stop.is_set():
                break
            new_ctx = self.detect_once()
            with self._lock:
                old_ctx = self._current_context
                if new_ctx != old_ctx:
                    self._current_context = new_ctx
                    changed = True
                else:
                    changed = False
            if changed and self._on_change:
                try:
                    self._on_change(old_ctx, new_ctx)
                except Exception:
                    pass
