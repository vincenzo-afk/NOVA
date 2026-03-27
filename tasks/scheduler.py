"""Persistent scheduler wrapper."""

from __future__ import annotations

import re

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore


class TaskScheduler:
    def __init__(self, db_url: str = "sqlite:///jarvis_jobs.sqlite"):
        self.scheduler = BackgroundScheduler(jobstores={"default": SQLAlchemyJobStore(url=db_url)})

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

    daily_match = re.search(r"(daily|every day)\s+at\s+(\d{1,2}):(\d{2})", text)
    if daily_match:
        return {"hour": int(daily_match.group(2)), "minute": int(daily_match.group(3))}

    weekday_match = re.search(
        r"every\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s+at\s+(\d{1,2}):(\d{2})",
        text,
    )
    if weekday_match:
        day = weekday_match.group(1)[:3]
        return {
            "day_of_week": day,
            "hour": int(weekday_match.group(2)),
            "minute": int(weekday_match.group(3)),
        }

    raise ValueError(f"Unsupported schedule text: {schedule_text}")
