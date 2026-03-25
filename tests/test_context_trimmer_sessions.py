from __future__ import annotations

from core.memory.context_trimmer import ContextTrimmer


def test_context_trimmer_summary_is_session_scoped():
    trimmer = ContextTrimmer(max_raw_turns=2)

    history_a = [
        {"role": "user", "content": "a1"},
        {"role": "assistant", "content": "a2"},
        {"role": "user", "content": "a3"},
    ]
    history_b = [
        {"role": "user", "content": "b1"},
        {"role": "assistant", "content": "b2"},
        {"role": "user", "content": "b3"},
    ]

    summary_a, _ = trimmer.trim(history_a, session_id="session_a")
    summary_b, _ = trimmer.trim(history_b, session_id="session_b")

    assert summary_a
    assert summary_b
    assert summary_a != summary_b
