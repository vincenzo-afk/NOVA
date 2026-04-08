"""Shared message bus for multi-agent collaboration."""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any


@dataclass
class BusMessage:
    from_agent: str
    to_agent: str
    msg_type: str
    payload: dict[str, Any]
    ts: float


class SharedMemoryBus:
    def __init__(self, path: str | Path = ".jarvis/shared_bus.jsonl"):
        self.path = Path(path)
        self._lock = threading.Lock()

    def publish(self, *, from_agent: str, to_agent: str, msg_type: str, payload: dict[str, Any]) -> dict:
        msg = BusMessage(
            from_agent=str(from_agent),
            to_agent=str(to_agent),
            msg_type=str(msg_type),
            payload=dict(payload or {}),
            ts=time.time(),
        )
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(asdict(msg), ensure_ascii=False) + "\n")
        return {"status": "ok", "message": asdict(msg)}

    def read(self, *, to_agent: str, limit: int = 50, include_broadcast: bool = True) -> list[dict]:
        if not self.path.exists():
            return []
        target = str(to_agent)
        rows: list[dict] = []
        with self._lock:
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                except Exception:
                    continue
                if not isinstance(item, dict):
                    continue
                dest = str(item.get("to_agent", ""))
                if dest == target or (include_broadcast and dest in {"*", "broadcast"}):
                    rows.append(item)
        return rows[-max(1, int(limit)) :]
