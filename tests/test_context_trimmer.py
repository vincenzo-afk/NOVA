from __future__ import annotations

from core.memory.context_trimmer import ContextTrimmer


def test_context_trimmer_keeps_recent_turns_and_summary():
    trimmer = ContextTrimmer(max_raw_turns=3)
    history = [
        {"role": "user", "content": "u1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "u2"},
        {"role": "assistant", "content": "a2"},
        {"role": "user", "content": "u3"},
    ]

    summary, recent = trimmer.trim(history)
    assert len(recent) == 3
    assert summary
    assert recent[0]["content"] == "u2"


def test_context_trimmer_falls_back_when_summarizer_returns_empty():
    trimmer = ContextTrimmer(max_raw_turns=2)
    history = [
        {"role": "user", "content": "one"},
        {"role": "assistant", "content": "two"},
        {"role": "user", "content": "three"},
    ]

    summary, recent = trimmer.trim(history, session_id="s1", summarizer=lambda _s: "")
    assert summary
    assert "user: one" in summary
    assert len(recent) == 2
