"""Proactive Goal Engine — Proactive Intelligence Tier 3.

Proposes goals from BehaviorModel predictions and IntentGraph transitions.
Proposed goals have status='proposed' and are auto-approved after a 5-minute
grace period if they pass guardrails (risk < 4) and AUTONOMY_ENABLED is True.
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Callable

log = logging.getLogger(__name__)

_GRACE_PERIOD_SECONDS = 300.0  # 5 minutes
_MAX_PROPOSED_GOALS = 10
_AUTO_APPROVE_RISK_MAX = 3     # only auto-approve risk score < 4


class ProactiveGoalEngine:
    """Synthesizes and proposes goals from context signals.

    Wire into NOVAApp by:
        self._proactive_goal_engine = ProactiveGoalEngine(
            propose_fn=self._propose_proactive_goal,
            risk_check_fn=lambda tool, args: guardrails.check(tool, args),
            behavior_model=self._behavior_model,
            intent_graph=self._intent_graph,
            template_library=self._template_library,
        )
    """

    def __init__(
        self,
        propose_fn: Callable[[dict], None],
        risk_check_fn: Callable[[str, dict], Any],
        behavior_model: Any | None = None,
        intent_graph: Any | None = None,
        template_library: Any | None = None,
        autonomy_enabled: bool = False,
    ):
        self._propose = propose_fn
        self._risk_check = risk_check_fn
        self._behavior_model = behavior_model
        self._intent_graph = intent_graph
        self._template_library = template_library
        self._autonomy_enabled = autonomy_enabled

        self._proposed: list[dict] = []  # list of proposed goal dicts
        self._lock = threading.Lock()

    # ── proposal creation ─────────────────────────────────────────────────────

    def propose_from_behavior(self) -> dict | None:
        """Propose a goal if BehaviorModel predicts a high-confidence activity."""
        if not self._behavior_model or not self._template_library:
            return None

        predictions = self._behavior_model.predict_next_activity(top_k=3)
        for activity, confidence in predictions:
            if confidence < 0.70:
                continue
            template = self._template_library.find_matching_template(activity)
            if template:
                return self._create_proposed_goal(
                    description=f"Predicted activity: {activity}",
                    steps=list(template.steps),
                    confidence=confidence,
                    source="behavior_model",
                )
        return None

    def propose_from_git_event(self, commit_message: str) -> dict | None:
        """Propose goal triggered by a new git commit (from FSWatcher)."""
        if not self._template_library:
            return None
        template = self._template_library.find_matching_template(
            f"run tests after commit {commit_message}"
        )
        if template:
            return self._create_proposed_goal(
                description=f"Run test suite — triggered by commit: {commit_message[:60]}",
                steps=list(template.steps),
                confidence=0.80,
                source="git_event",
            )
        # Fallback: propose a generic test-run goal
        return self._create_proposed_goal(
            description=f"Run test suite since you just committed: {commit_message[:60]}",
            steps=[{"tool": "win32.launch_process", "args": {"command": "python -m pytest"}}],
            confidence=0.75,
            source="git_event",
        )

    def propose_from_context_transition(self, from_ctx: str, to_ctx: str) -> dict | None:
        """Propose goal when WorkContextTracker detects an app transition."""
        if not self._template_library:
            return None
        query = f"switch from {from_ctx} to {to_ctx}"
        template = self._template_library.find_matching_template(query)
        if not template:
            return None
        return self._create_proposed_goal(
            description=f"Context switch: {from_ctx} → {to_ctx}",
            steps=list(template.steps),
            confidence=0.65,
            source="context_transition",
        )

    def _create_proposed_goal(
        self,
        description: str,
        steps: list[dict],
        confidence: float,
        source: str,
    ) -> dict | None:
        with self._lock:
            if len(self._proposed) >= _MAX_PROPOSED_GOALS:
                # Evict oldest
                self._proposed.pop(0)

        goal = {
            "id": str(uuid.uuid4()),
            "goal": description,
            "steps": steps,
            "status": "proposed",
            "proposed_at": time.time(),
            "confidence": confidence,
            "source": source,
            "replan_count": 0,
        }
        with self._lock:
            self._proposed.append(goal)

        try:
            self._propose(goal)
        except Exception as exc:
            log.warning("[proactive_goal_engine] propose_fn failed: %s", exc)

        return goal

    # ── auto-approval (called from autonomy loop) ─────────────────────────────

    def drain_auto_approvable(
        self,
        running_goal_count: int,
        max_running: int = 3,
    ) -> list[dict]:
        """Return goals that have waited ≥ 5 min and pass risk checks.
        
        Caller is responsible for adding returned goals to the goals list.
        """
        if not self._autonomy_enabled or running_goal_count >= max_running:
            return []

        now = time.time()
        approvable: list[dict] = []

        with self._lock:
            remaining: list[dict] = []
            for g in self._proposed:
                proposed_at = g.get("proposed_at")
                if not isinstance(proposed_at, (int, float)):
                    # Malformed item: reset age anchor so it can still progress instead of stalling forever.
                    proposed_at = now
                    g["proposed_at"] = proposed_at
                age = now - proposed_at
                if age < _GRACE_PERIOD_SECONDS:
                    remaining.append(g)
                    continue

                # Run risk check on first step
                steps = g.get("steps") or []
                if not steps:
                    continue
                first_step = steps[0]
                try:
                    result = self._risk_check(
                        first_step.get("tool", ""),
                        first_step.get("args", {}),
                    )
                    score = getattr(result, "score", 10)
                    if score <= _AUTO_APPROVE_RISK_MAX:
                        g["status"] = "pending"
                        approvable.append(g)
                    else:
                        g["status"] = "proposed"  # keep waiting for human
                        remaining.append(g)
                except Exception:
                    remaining.append(g)

            self._proposed = remaining

        return approvable
