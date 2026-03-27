"""Proactive phone watcher using ADB screenshots."""

from __future__ import annotations

import hashlib
import re
import tempfile
import threading
import time
from typing import Callable

from core.llm.fallback import NetworkState
from control.adb.adb_client import ADBClient
from vision.gemini_vision import analyze_image


_PHONE_KEYWORDS = {
    "incoming call",
    "missed call",
    "new message",
    "message",
    "error",
    "stopped",
    "not responding",
    "permission",
    "failed",
}


class PhoneWatcher:
    def __init__(
        self,
        adb: ADBClient,
        interval_seconds: float = 12.0,
        cooldown_seconds: float = 120.0,
        on_alert: Callable[[str], None] | None = None,
    ):
        self.adb = adb
        self.interval_seconds = max(2.0, float(interval_seconds))
        self.cooldown_seconds = max(10.0, float(cooldown_seconds))
        self.on_alert = on_alert or (lambda msg: print(msg))
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._last_alert_ts = 0.0
        self._last_notifications_digest = ""
        self._last_sms_digest = ""

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.is_running():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

    def restart(self) -> None:
        self.stop()
        self.start()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception:
                pass
            time.sleep(self.interval_seconds)

    def _tick(self) -> None:
        if not NetworkState.is_online():
            return
        try:
            devices = self.adb.devices()
        except Exception:
            return
        if not devices:
            return

        self._poll_notifications()
        self._poll_sms()

        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp_path = tmp.name
            self.adb.screenshot_to_local(tmp_path)
            with open(tmp_path, "rb") as fh:
                image_bytes = fh.read()
        finally:
            if tmp_path:
                import os as _os
                try:
                    _os.unlink(tmp_path)
                except Exception:
                    pass

        analysis = analyze_image(image_bytes)
        message = self._detect_issue(analysis)
        if not message:
            return

        now = time.time()
        if now - self._last_alert_ts < self.cooldown_seconds:
            return
        self._last_alert_ts = now
        self.on_alert(message)

    def _poll_notifications(self) -> None:
        try:
            raw = self.adb.notifications_dump()
        except Exception:
            return
        digest = hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()
        if digest == self._last_notifications_digest:
            return
        self._last_notifications_digest = digest
        summary = self._summarize_notifications(raw)
        if summary:
            self.on_alert(summary)

    def _poll_sms(self) -> None:
        try:
            raw = self.adb.sms_dump()
        except Exception:
            return
        digest = hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()
        if digest == self._last_sms_digest:
            return
        self._last_sms_digest = digest
        summary = self._summarize_sms(raw)
        if summary:
            self.on_alert(summary)

    def _detect_issue(self, analysis: dict) -> str:
        if not isinstance(analysis, dict):
            return ""
        errors = analysis.get("detected_errors") or []
        if errors:
            return f"Phone alert: {', '.join(str(e) for e in errors)}"
        combined = " ".join(
            [
                str(analysis.get("scene_type", "")),
                str(analysis.get("active_app", "")),
                " ".join(str(x) for x in analysis.get("notable_elements", []) or []),
            ]
        ).lower()
        if any(keyword in combined for keyword in _PHONE_KEYWORDS):
            return "Phone alert: I spotted a possible issue or notification. Want help?"
        return ""

    def _summarize_notifications(self, raw: str) -> str:
        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        if not lines:
            return ""

        combined = " ".join(lines).lower()
        if "incoming call" in combined or "call" in combined and "ring" in combined:
            return "Phone alert: incoming call detected. Want me to help answer or silence it?"
        if "missed call" in combined:
            return "Phone alert: you have a missed call notification."

        hits: list[str] = []
        for line in lines[:20]:
            lower = line.lower()
            if any(keyword in lower for keyword in _PHONE_KEYWORDS):
                hits.append(line)
        if hits:
            joined = "; ".join(hits[:3])
            return f"Phone alert: new notifications on the phone -> {joined}"

        if any(token in combined for token in ("android", "notification", "alert")):
            return "Phone alert: the phone has new notifications."
        return ""

    def _summarize_sms(self, raw: str) -> str:
        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        if not lines:
            return ""

        entries: list[str] = []
        for line in lines[-10:]:
            lower = line.lower()
            if any(token in lower for token in ("body:", "body=", "address:", "address=")):
                entries.append(line)
        if not entries:
            return ""

        cleaned = []
        for entry in entries:
            text = re.sub(r"\s+", " ", entry)
            cleaned.append(text)
        return "Phone alert: new SMS activity -> " + "; ".join(cleaned[:3])
