"""File-claim conflict resolver for A2A collaboration."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any


class ConflictResolver:
    def __init__(self, lock_path: str | Path = ".jarvis/a2a_file_locks.json"):
        self.lock_path = Path(lock_path)
        self._lock = threading.Lock()

    def claim_file(self, *, agent_name: str, filepath: str) -> dict[str, Any]:
        path = str(filepath)
        with self._lock:
            data = self._load()
            holder = data.get(path)
            if holder and holder.get("agent_name") != agent_name:
                winner = min(str(holder.get("agent_name")), str(agent_name))
                paused = agent_name if winner != agent_name else holder.get("agent_name")
                return {
                    "status": "conflict",
                    "path": path,
                    "held_by": holder.get("agent_name"),
                    "winner": winner,
                    "paused_agent": paused,
                }
            data[path] = {"agent_name": str(agent_name), "ts": int(time.time())}
            self._save(data)
            return {"status": "claimed", "path": path, "agent_name": agent_name}

    def release_file(self, *, agent_name: str, filepath: str) -> dict[str, Any]:
        path = str(filepath)
        with self._lock:
            data = self._load()
            holder = data.get(path)
            if not holder:
                return {"status": "not_found", "path": path}
            if str(holder.get("agent_name")) != str(agent_name):
                return {"status": "not_owner", "path": path, "held_by": holder.get("agent_name")}
            data.pop(path, None)
            self._save(data)
            return {"status": "released", "path": path}

    def current_locks(self) -> dict[str, Any]:
        with self._lock:
            return self._load()

    def _load(self) -> dict[str, Any]:
        if not self.lock_path.exists():
            return {}
        try:
            data = json.loads(self.lock_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _save(self, data: dict[str, Any]) -> None:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self.lock_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
