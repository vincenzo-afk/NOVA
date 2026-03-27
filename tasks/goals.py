"""Goal decomposition engine with loop guards and step executor."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterable

from core.tools.dispatcher import Dispatcher, ToolCall


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


@dataclass
class GoalResult:
    status: str
    reason: str
    results: list[dict]
    next_index: int = 0


class GoalRunner:
    """Executes a list of tool steps with cycle detection and step limits."""

    def __init__(self, dispatcher: Dispatcher):
        self.dispatcher = dispatcher

    def run(
        self,
        steps: Iterable[dict[str, Any]],
        *,
        max_steps: int = 20,
        dry_run: bool = False,
        start_index: int = 0,
    ) -> GoalResult:
        guard = GoalRun(max_steps=max_steps)
        results: list[dict] = []

        indexed_steps = list(steps)
        if start_index < 0:
            start_index = 0
        if start_index >= len(indexed_steps):
            return GoalResult(status="completed", reason="no_remaining_steps", results=[], next_index=start_index)

        for idx, step in enumerate(indexed_steps[start_index:], start=start_index):
            tool = step.get("tool") or step.get("name")
            args = step.get("args") or {}
            if not tool:
                return GoalResult(
                    status="failed",
                    reason="missing_tool_name",
                    results=results,
                    next_index=idx,
                )

            can_execute, reason = guard.can_execute(tool, args)
            if not can_execute:
                return GoalResult(status="stopped", reason=reason, results=results, next_index=idx)

            guard.record(tool, args)
            call = ToolCall(tool=tool, args=args)
            result = self.dispatcher.execute(call, dry_run=dry_run)
            results.append(result)

        return GoalResult(status="completed", reason="ok", results=results, next_index=len(indexed_steps))
