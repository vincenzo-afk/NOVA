"""Reasoning and ambiguity utilities."""

from __future__ import annotations

import re

from config.constants import DEFAULT_AMBIGUITY_THRESHOLD


_COT_PREFIX = (
    "Reason internally step by step, but never reveal private chain-of-thought. "
    "Return concise final answers and actionable plans."
)

_AMBIGUOUS_TERMS = {
    "this",
    "that",
    "it",
    "there",
    "thing",
    "stuff",
    "later",
    "soon",
    "maybe",
    "somewhere",
}

_ACTION_VERBS = {
    "delete",
    "remove",
    "send",
    "launch",
    "open",
    "close",
    "run",
    "install",
    "kill",
    "format",
    "move",
}


def build_system_prompt(base: str, dispatcher=None, emotion: str | None = None) -> str:
    prompt = f"{base}\n\n{_COT_PREFIX}"
    if emotion:
        prompt += f"\n\nCurrent emotional tone: {emotion}."
    if dispatcher:
        prompt += "\n\n" + dispatcher.get_tool_schema_prompt()
    return prompt


def ambiguity_score(user_text: str) -> float:
    text = user_text.lower().strip()
    if not text:
        return 1.0

    tokens = re.findall(r"[a-zA-Z0-9_]+", text)
    token_count = len(tokens)
    ambiguous_hits = sum(1 for t in tokens if t in _AMBIGUOUS_TERMS)
    action_hits = sum(1 for t in tokens if t in _ACTION_VERBS)

    score = 0.0
    if token_count <= 3:
        score += 0.35
    if ambiguous_hits > 0:
        score += min(0.4, ambiguous_hits * 0.15)
    if action_hits > 0 and ambiguous_hits > 0:
        score += 0.25
    if "?" in text:
        score -= 0.1

    return max(0.0, min(1.0, score))


def needs_clarification(user_text: str, threshold: float = DEFAULT_AMBIGUITY_THRESHOLD) -> bool:
    return ambiguity_score(user_text) >= threshold


def clarifying_question(user_text: str) -> str:
    return (
        "I want to do this correctly. Did you mean a specific target or action? "
        f"For example, if you said '{user_text}', tell me exactly what object/app/file I should use."
    )
