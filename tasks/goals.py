"""Goal decomposition engine with loop guards and step executor.

Fixes applied:
- 1.5: GoalRunner now checks guardrails risk for each step individually.
       High-risk steps without a confirm_callback will block and halt the run.
- 1.7: Configurable minimum inter-step delay to prevent API hammering.
"""

from __future__ import annotations

import json
import threading
import time
from concurrent.futures import CancelledError, ThreadPoolExecutor, TimeoutError as FuturesTimeout
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

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
    """Executes a list of tool steps with cycle detection, step limits, and per-step guardrails.

    Fix 1.5: every step is individually checked by guardrails. High-risk steps without
    a confirm_callback will be blocked and halt the goal (no silent bypass).
    Fix 1.7: `step_delay_seconds` adds a minimum inter-step pause to prevent burst API hammering.
    """

    def __init__(
        self,
        dispatcher: Dispatcher,
        confirm_callback: Callable[[str], bool] | None = None,
        force_confirm_medium: bool = False,
        step_delay_seconds: float = 0.0,
        step_timeout_seconds: float = 60.0,
        sleep_fn: Callable[[float], None] = time.sleep,
    ):
        self.dispatcher = dispatcher
        self.confirm_callback = confirm_callback  # fix 1.5
        self.force_confirm_medium = force_confirm_medium
        self.step_delay_seconds = max(0.0, step_delay_seconds)  # fix 1.7
        self.step_timeout_seconds = max(1.0, float(step_timeout_seconds))
        self._sleep_fn = sleep_fn
        self._executor = ThreadPoolExecutor(max_workers=1)
        self._closed = False
        self._executor_lock = threading.Lock()

    def close(self, *, cancel_futures: bool = False) -> None:
        with self._executor_lock:
            self._closed = True
            try:
                self._executor.shutdown(wait=False, cancel_futures=cancel_futures)
            except TypeError:
                self._executor.shutdown(wait=False)

    def run(
        self,
        steps: Iterable[dict[str, Any]],
        *,
        max_steps: int = 20,
        dry_run: bool = False,
        start_index: int = 0,
        on_step: Callable[[int, dict[str, Any]], None] | None = None,
        confirm_callback: Callable[[str], bool] | None = None,
        should_continue: Callable[[], bool] | None = None,
    ) -> GoalResult:
        guard = GoalRun(max_steps=max_steps)
        results: list[dict] = []

        indexed_steps = list(steps)
        if start_index < 0:
            start_index = 0
        if start_index >= len(indexed_steps):
            return GoalResult(status="completed", reason="no_remaining_steps", results=[], next_index=start_index)

        for idx, step in enumerate(indexed_steps[start_index:], start=start_index):
            if should_continue is not None:
                try:
                    if not should_continue():
                        return GoalResult(
                            status="cancelled",
                            reason="cancelled_by_user",
                            results=results,
                            next_index=idx,
                        )
                except Exception:
                    return GoalResult(
                        status="failed",
                        reason="cancellation_check_failed",
                        results=results,
                        next_index=idx,
                    )
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

            # fix 1.5: per-step guardrails check (also during dry_run).
            from safety.guardrails import guardrails
            call = ToolCall(tool=tool, args=args)
            risk = guardrails.check(call)
            if self.force_confirm_medium and risk.level == "medium":
                risk.level = "high"
                risk.requires_confirmation = True
                risk.auto_confirm_seconds = None
            authorized = guardrails.authorize(
                call,
                risk,
                confirm_callback=confirm_callback if confirm_callback is not None else self.confirm_callback,
                dry_run=dry_run,
            )
            if dry_run or authorized.reason == "dry_run":
                guard.record(tool, args)
                results.append(
                    {
                        "status": "dry_run",
                        "tool": tool,
                        "args": args,
                        "risk": authorized.score,
                        "level": authorized.level,
                    }
                )
                continue
            if authorized.blocked:
                return GoalResult(
                    status="blocked",
                    reason=f"step {idx} blocked by guardrails: {authorized.reason}",
                    results=results,
                    next_index=idx,
                )

            guard.record(tool, args)
            with self._executor_lock:
                if self._closed:
                    return GoalResult(
                        status="failed",
                        reason="runner_closed",
                        results=results,
                        next_index=idx,
                    )
                if guardrails.is_emergency_stopped():
                    return GoalResult(
                        status="blocked",
                        reason="emergency_stop_active",
                        results=results,
                        next_index=idx,
                    )
                try:
                    future = self._executor.submit(self.dispatcher.execute, call, None, None, dry_run, True)
                except RuntimeError:
                    self._closed = True
                    return GoalResult(
                        status="failed",
                        reason="runner_closed",
                        results=results,
                        next_index=idx,
                    )
            try:
                result = future.result(timeout=self.step_timeout_seconds)
            except CancelledError:
                return GoalResult(
                    status="failed",
                    reason="step_cancelled",
                    results=results,
                    next_index=idx,
                )
            except FuturesTimeout:
                future.cancel()
                # Timeout does not reliably stop an already-running worker thread.
                # Replace the executor so subsequent steps/runs don't deadlock behind it.
                with self._executor_lock:
                    try:
                        self._executor.shutdown(wait=False, cancel_futures=True)
                    except TypeError:
                        self._executor.shutdown(wait=False)
                    self._executor = ThreadPoolExecutor(max_workers=1)
                return GoalResult(
                    status="failed",
                    reason=f"step_timeout_seconds_exceeded:{self.step_timeout_seconds}",
                    results=results,
                    next_index=idx,
                )
            results.append(result)
            if on_step is not None:
                try:
                    on_step(idx, result)
                except Exception:
                    pass

            # fix 1.7: inter-step delay
            if self.step_delay_seconds > 0 and idx < len(indexed_steps) - 1:
                self._sleep_fn(self.step_delay_seconds)

        if dry_run:
            return GoalResult(status="dry_run", reason="dry_run", results=results, next_index=len(indexed_steps))
        return GoalResult(status="completed", reason="ok", results=results, next_index=len(indexed_steps))
