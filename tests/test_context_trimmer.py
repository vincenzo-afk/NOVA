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
