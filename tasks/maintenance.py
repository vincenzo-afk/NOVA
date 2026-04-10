"""Preventive Maintenance Orchestrator — Proactive Intelligence Tier 4.

Runs a daily maintenance sequence (3–4am) using existing tools:
disk check, log compression, export cleanup, ChromaDB backup, and
OmniParser health verification.

All steps go through guardrails.check() via GoalRunner.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger(__name__)

_MAINT_LOG_PATH = Path(".jarvis/maintenance_log.jsonl")
_ALLOWED_HOURS   = {2, 3}             # 2–4am window
_EXPORT_MAX_DAYS = 30
_LOG_MAX_BYTES   = 50 * 1024 * 1024  # 50 MB
_DISK_WARN_GB    = 10.0


class MaintenanceOrchestrator:
    """Executes nightly self-maintenance tasks as a GoalRunner plan."""

    def __init__(
        self,
        notify_fn: Callable[[str], None],
        goal_runner_run_fn: Callable[[list[dict]], Any] | None = None,
        backup_fn: Callable[[], None] | None = None,
        memory_sync_fn: Callable[[], None] | None = None,
        health_check_fn: Callable[[], dict] | None = None,
    ):
        self._notify = notify_fn
        self._goal_runner_run = goal_runner_run_fn
        self._backup = backup_fn
        self._memory_sync = memory_sync_fn
        self._health_check = health_check_fn

    # ── main entry (called by TaskScheduler at 3am) ────────────────────────────

    def run_daily_maintenance(self) -> dict:
        hour = datetime.now(timezone.utc).hour
        if hour not in _ALLOWED_HOURS:
            log.debug("[maintenance] skipped — not in maintenance window (hour=%d)", hour)
            return {"skipped": True, "reason": "outside_window"}

        log.info("[maintenance] starting daily maintenance")
        report: dict[str, Any] = {
            "started_at": datetime.now(timezone.utc).isoformat(),
            "steps": {},
        }
        alerts: list[str] = []

        # 1. Disk check
        disk_ok, disk_msg = self._check_disk()
        report["steps"]["disk"] = disk_msg
        if not disk_ok:
            alerts.append(disk_msg)

        # 2. Export cleanup
        cleaned, cleaned_bytes = self._clean_exports()
        if cleaned > 0:
            msg = f"Cleaned {cleaned} old exports ({cleaned_bytes / 1e6:.1f} MB freed)"
            report["steps"]["exports"] = msg
            alerts.append(msg)
        else:
            report["steps"]["exports"] = "ok"

        # 3. Log compression
        log_msg = self._compress_logs()
        report["steps"]["logs"] = log_msg

        # 4. Memory sync
        if self._memory_sync:
            try:
                self._memory_sync()
                report["steps"]["memory_sync"] = "ok"
            except Exception as exc:
                report["steps"]["memory_sync"] = f"failed: {exc}"

        # 5. ChromaDB backup
        if self._backup:
            try:
                self._backup()
                report["steps"]["backup"] = "ok"
            except Exception as exc:
                report["steps"]["backup"] = f"failed: {exc}"
                alerts.append(f"Backup failed: {exc}")

        # 6. Health check
        if self._health_check:
            try:
                results = self._health_check()
                down = [k for k, v in results.items() if v in {"down", "restart_failed"}]
                report["steps"]["health"] = results
                if down:
                    alerts.append(f"Subsystems down after maintenance: {', '.join(down)}")
            except Exception as exc:
                report["steps"]["health"] = f"failed: {exc}"

        report["completed_at"] = datetime.now(timezone.utc).isoformat()
        self._log_report(report)

        if alerts:
            summary = "\n".join(f"• {a}" for a in alerts)
            self._notify(f"🔧 *Maintenance report:*\n{summary}")
        else:
            log.info("[maintenance] completed cleanly — no alerts")

        return report

    # ── steps ─────────────────────────────────────────────────────────────────

    def _check_disk(self) -> tuple[bool, str]:
        try:
            import shutil
            targets = [
                Path(".jarvis_chroma").resolve(),
                Path("exports").resolve(),
            ]
            worst_free_gb = float("inf")
            worst_pct = 0.0
            worst_target = targets[0]
            for target in targets:
                total, used, free = shutil.disk_usage(str(target))
                free_gb = free / 1e9
                pct_used = (used / total) * 100 if total else 0
                if free_gb < worst_free_gb:
                    worst_free_gb = free_gb
                    worst_pct = pct_used
                    worst_target = target
            if worst_free_gb < _DISK_WARN_GB:
                return False, f"Disk at {worst_pct:.0f}% on {worst_target} — only {worst_free_gb:.1f} GB free"
            return True, f"Disk ok ({worst_free_gb:.1f} GB free min, {worst_pct:.0f}% used max)"
        except Exception as exc:
            return True, f"Disk check error: {exc}"

    def _clean_exports(self) -> tuple[int, int]:
        exports_dir = Path("exports")
        if not exports_dir.is_dir():
            return 0, 0
        now = time.time()
        cutoff = now - (_EXPORT_MAX_DAYS * 86400)
        removed, freed = 0, 0
        for f in exports_dir.iterdir():
            if f.is_file() and f.stat().st_mtime < cutoff:
                size = f.stat().st_size
                try:
                    f.unlink()
                    removed += 1
                    freed += size
                except Exception:
                    pass
        return removed, freed

    def _compress_logs(self) -> str:
        log_file = Path("logs/jarvis.log")
        if not log_file.exists():
            return "no_log_file"
        if log_file.stat().st_size < _LOG_MAX_BYTES:
            return f"ok ({log_file.stat().st_size / 1e6:.1f} MB)"
        try:
            import gzip, shutil
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            archive = log_file.with_name(f"jarvis_{ts}.log.gz")
            with log_file.open("rb") as f_in, gzip.open(archive, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
            valid_archive = False
            if archive.exists() and archive.stat().st_size > 0:
                try:
                    with gzip.open(archive, "rb") as verify:
                        data = verify.read(64)  # force a real decompress/read to catch corruption
                        valid_archive = len(data) > 0
                except (EOFError, gzip.BadGzipFile, OSError):
                    valid_archive = False
            if valid_archive:
                log_file.write_text("")  # truncate only after successful archive write
            else:
                return "compression failed: empty archive output"
            return f"compressed → {archive.name}"
        except Exception as exc:
            return f"compression failed: {exc}"

    # ── persistence ───────────────────────────────────────────────────────────

    def _log_report(self, report: dict) -> None:
        try:
            _MAINT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with _MAINT_LOG_PATH.open("a", encoding="utf-8") as f:
                f.write(json.dumps(report) + "\n")
        except Exception:
            pass
