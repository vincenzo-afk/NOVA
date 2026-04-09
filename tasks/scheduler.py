"""Persistent scheduler wrapper."""

from __future__ import annotations

import os
import re
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore


from config.settings import settings


class TaskScheduler:
    def __init__(self, db_url: str | None = None):
        from sqlalchemy import create_engine
        if db_url is None:
            data_dir = Path(os.getenv("DATA_DIR", settings.DATA_DIR)).expanduser().resolve()
            data_dir.mkdir(parents=True, exist_ok=True)
            db_url = f"sqlite:///{data_dir}/jarvis_jobs.sqlite"
        connect_args = {"timeout": 30} if db_url.startswith("sqlite") else {}
        engine = create_engine(db_url, connect_args=connect_args)
        self.scheduler = BackgroundScheduler(
            jobstores={"default": SQLAlchemyJobStore(engine=engine)}
        )


    def start(self) -> None:
        if not self.scheduler.running:
            self.scheduler.start()

    def stop(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)

    def add_interval(self, fn, seconds: int, job_id: str) -> None:
        self.scheduler.add_job(fn, "interval", seconds=seconds, id=job_id, replace_existing=True)

    def add_cron(self, fn, cron: dict, job_id: str) -> None:
        self.scheduler.add_job(fn, "cron", id=job_id, replace_existing=True, **cron)

    def add_from_text(self, fn, schedule_text: str, job_id: str) -> dict:
        cron = parse_schedule_text(schedule_text)
        if "interval_seconds" in cron:
            self.add_interval(fn, seconds=cron["interval_seconds"], job_id=job_id)
        else:
            self.add_cron(fn, cron=cron, job_id=job_id)
        return cron

    def list_jobs(self) -> list[str]:
        return [job.id for job in self.scheduler.get_jobs()]

    def list_jobs_detailed(self) -> list[dict]:
        jobs = []
        for job in self.scheduler.get_jobs():
            jobs.append(
                {
                    "id": job.id,
                    "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None,
                    "trigger": str(job.trigger),
                }
            )
        return jobs

    def remove_job(self, job_id: str) -> bool:
        try:
            self.scheduler.remove_job(job_id)
            return True
        except Exception:
            return False


def parse_schedule_text(schedule_text: str) -> dict:
    text = schedule_text.strip().lower()
    interval_match = re.search(r"every\s+(\d+)\s+(second|seconds|minute|minutes|hour|hours)", text)
    if interval_match:
        n = int(interval_match.group(1))
        unit = interval_match.group(2)
        seconds = n
        if "minute" in unit:
            seconds = n * 60
        elif "hour" in unit:
            seconds = n * 3600
        return {"interval_seconds": max(1, seconds)}

    def _normalize_time(hour_str: str, min_str: str, ampm: str | None) -> tuple[int, int]:
        h = int(hour_str)
        m = int(min_str)
        if m < 0 or m > 59:
            raise ValueError("minute must be between 00 and 59")
        if ampm:
            if h < 1 or h > 12:
                raise ValueError("hour must be 1-12 for am/pm format")
            if ampm == "pm" and h < 12:
                h += 12
            if ampm == "am" and h == 12:
                h = 0
        else:
            if h < 0 or h > 23:
                raise ValueError("hour must be 0-23 for 24h format")
        return h, m

    daily_match = re.search(r"(daily|every day)\s+at\s+(\d{1,2}):(\d{2})(?:\s*(am|pm))?", text)
    if daily_match:
        h, m = _normalize_time(daily_match.group(2), daily_match.group(3), daily_match.group(4))
        return {"hour": h, "minute": m}

    weekday_match = re.search(
        r"every\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s+at\s+(\d{1,2}):(\d{2})(?:\s*(am|pm))?",
        text,
    )
    if weekday_match:
        weekday_name = weekday_match.group(1)
        weekday_map = {
            "monday": "mon",
            "tuesday": "tue",
            "wednesday": "wed",
            "thursday": "thu",
            "friday": "fri",
            "saturday": "sat",
            "sunday": "sun",
        }
        day = weekday_map[weekday_name]
        h, m = _normalize_time(weekday_match.group(2), weekday_match.group(3), weekday_match.group(4))
        return {
            "day_of_week": day,
            "hour": h,
            "minute": m,
        }

    raise ValueError(f"Unsupported schedule text: {schedule_text}")
