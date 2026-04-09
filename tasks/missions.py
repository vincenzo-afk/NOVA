"""Recurring autonomous mission manager (Phase 16)."""

from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from tasks.scheduler import TaskScheduler, parse_schedule_text


_MISSIONS_PATH = Path(".jarvis/missions.json")


@dataclass
class Mission:
    name: str
    schedule: str
    goal: str
    enabled: bool = True
    created_at: float = 0.0
    last_trigger_at: float = 0.0


class MissionManager:
    def __init__(
        self,
        scheduler: TaskScheduler,
        enqueue_goal_fn: Callable[[str], dict],
        persist_path: Path = _MISSIONS_PATH,
    ):
        self.scheduler = scheduler
        self.enqueue_goal_fn = enqueue_goal_fn
        self._path = persist_path
        self._missions: dict[str, Mission] = {}
        self._load()
        self._ensure_scheduled()

    def add_mission(self, name: str, schedule: str, goal: str, enabled: bool = True) -> dict:
        mission_name = self._normalize_name(name)
        if not mission_name:
            return {"status": "error", "reason": "mission_name_required"}
        normalized_schedule = str(schedule or "").strip()
        if not normalized_schedule:
            return {"status": "error", "reason": "schedule_required"}
        if not goal.strip():
            return {"status": "error", "reason": "goal_required"}
        try:
            parse_schedule_text(normalized_schedule)
        except Exception as exc:
            return {"status": "error", "reason": f"invalid_schedule:{exc}"}
        mission = Mission(
            name=mission_name,
            schedule=normalized_schedule,
            goal=goal.strip(),
            enabled=bool(enabled),
            created_at=time.time(),
        )
        existing = self._missions.get(mission_name)
        self._missions[mission_name] = mission
        try:
            self._schedule_one(mission)
        except Exception as exc:
            if existing is None:
                self._missions.pop(mission_name, None)
            else:
                self._missions[mission_name] = existing
            return {"status": "error", "reason": f"schedule_register_failed:{exc}"}
        self._save()
        return {"status": "ok", "mission": asdict(mission)}

    def list_missions(self) -> list[dict]:
        return [asdict(m) for m in sorted(self._missions.values(), key=lambda x: x.name)]

    def enable_mission(self, name: str, enabled: bool) -> dict:
        key = self._normalize_name(name)
        mission = self._missions.get(key)
        if not mission:
            return {"status": "error", "reason": "mission_not_found", "name": key}
        mission.enabled = bool(enabled)
        self._save()
        if mission.enabled:
            self._schedule_one(mission)
        else:
            self.scheduler.remove_job(self._job_id(mission.name))
        return {"status": "ok", "mission": asdict(mission)}

    def remove_mission(self, name: str) -> dict:
        key = self._normalize_name(name)
        if key not in self._missions:
            return {"status": "error", "reason": "mission_not_found", "name": key}
        self._missions.pop(key, None)
        self.scheduler.remove_job(self._job_id(key))
        self._save()
        return {"status": "ok", "removed": key}

    def run_mission_now(self, name: str) -> dict:
        key = self._normalize_name(name)
        mission = self._missions.get(key)
        if not mission:
            return {"status": "error", "reason": "mission_not_found", "name": key}
        return self._execute(mission)

    def parse_and_add_from_text(self, text: str) -> dict:
        raw = text.strip()
        # Example: "schedule mission morning_brief every day at 08:00 to summarize..."
        m = re.search(
            r"schedule\s+mission\s+([a-zA-Z0-9_-]+)\s+every\s+(.+?)\s+to\s+(.+)$",
            raw,
            flags=re.IGNORECASE,
        )
        if m:
            name = m.group(1).strip()
            schedule = "every " + m.group(2).strip()
            goal = m.group(3).strip()
            return self.add_mission(name=name, schedule=schedule, goal=goal, enabled=True)
        # Also support: "schedule mission x daily at 08:00 to ..."
        m2 = re.search(
            r"schedule\s+mission\s+([a-zA-Z0-9_-]+)\s+(daily\s+at\s+.+?)\s+to\s+(.+)$",
            raw,
            flags=re.IGNORECASE,
        )
        if m2:
            name = m2.group(1).strip()
            schedule = m2.group(2).strip()
            goal = m2.group(3).strip()
            return self.add_mission(name=name, schedule=schedule, goal=goal, enabled=True)
        return {"status": "error", "reason": "parse_failed"}

    def _ensure_scheduled(self) -> None:
        for mission in self._missions.values():
            self._schedule_one(mission)

    def _schedule_one(self, mission: Mission) -> None:
        jid = self._job_id(mission.name)
        self.scheduler.remove_job(jid)
        if not mission.enabled:
            return
        self.scheduler.add_from_text(
            fn=lambda mname=mission.name: self._execute_by_name(mname),
            schedule_text=mission.schedule,
            job_id=jid,
        )

    def _execute_by_name(self, mission_name: str) -> None:
        mission = self._missions.get(self._normalize_name(mission_name))
        if not mission or not mission.enabled:
            return
        self._execute(mission)

    def _execute(self, mission: Mission) -> dict:
        mission.last_trigger_at = time.time()
        self._save()
        result = self.enqueue_goal_fn(mission.goal)
        return {"status": "ok", "mission": mission.name, "goal_result": result}

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            return
        for item in raw if isinstance(raw, list) else []:
            if not isinstance(item, dict):
                continue
            name = self._normalize_name(str(item.get("name", "")))
            if not name:
                continue
            self._missions[name] = Mission(
                name=name,
                schedule=str(item.get("schedule", "every day at 08:00")),
                goal=str(item.get("goal", "")),
                enabled=bool(item.get("enabled", True)),
                created_at=float(item.get("created_at", 0.0) or 0.0),
                last_trigger_at=float(item.get("last_trigger_at", 0.0) or 0.0),
            )

    def _save(self) -> None:
        import tempfile
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = [asdict(m) for m in self._missions.values()]
        content = json.dumps(payload, ensure_ascii=False, indent=2)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(self._path.parent),
            delete=False,
            suffix=".tmp",
        ) as tmp:
            tmp.write(content)
            tmp.flush()
            tmp_path = Path(tmp.name)
        tmp_path.replace(self._path)

    @staticmethod
    def _job_id(name: str) -> str:
        return f"mission_{name}"

    @staticmethod
    def _normalize_name(name: str) -> str:
        slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", (name or "").strip().lower())
        return slug.strip("_")[:64]
