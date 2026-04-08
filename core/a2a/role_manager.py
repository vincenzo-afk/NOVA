"""Advisory role assignment for A2A peers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RoleDecision:
    role: str
    rationale: str


def assign_role(*, tools: list[str], can_run_tests: bool, has_git: bool, has_rag: bool) -> RoleDecision:
    tool_set = {t.lower() for t in (tools or [])}
    if can_run_tests:
        return RoleDecision(role="tester", rationale="pytest tooling available")
    if has_git and any("win32_api.write" in t or "browser" in t for t in tool_set):
        return RoleDecision(role="developer", rationale="edit-capable toolchain with git")
    if has_rag:
        return RoleDecision(role="documenter", rationale="RAG/document tooling available")
    return RoleDecision(role="reviewer", rationale="default analysis/review role")
