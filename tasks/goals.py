"""Goal decomposition engine with loop guards."""

from __future__ import annotations

import json
from dataclasses import dataclass, field


def _step_key(tool: str, args: dict) -> str:
    return f"{tool}:{json.dumps(args, sort_keys=True, ensure_ascii=False)}"


def detect_cycle(previous_steps: list[tuple[str, dict]], tool: str, args: dict) -> bool:
    current = _step_key(tool, args)
    return any(_step_key(prev_tool, prev_args) == current for prev_tool, prev_args in previous_steps)


def enforce_max_steps(step_count: int, max_steps: int = 20) -> bool:
    return step_count >= max_steps


@dataclass
class GoalRun:
    max_steps: int = 20
    steps: list[tuple[str, dict]] = field(default_factory=list)

    def can_execute(self, tool: str, args: dict) -> tuple[bool, str]:
        if enforce_max_steps(len(self.steps), self.max_steps):
            return False, f"Reached max_steps={self.max_steps}"
        if detect_cycle(self.steps, tool, args):
            return False, f"Cycle detected for tool={tool} args={args}"
        return True, "ok"

    def record(self, tool: str, args: dict) -> None:
        self.steps.append((tool, args))
