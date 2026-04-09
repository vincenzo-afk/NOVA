from __future__ import annotations

import json
from pathlib import Path

from tasks.pattern_shortcuts import PatternShortcutCompiler


def _write_log(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def test_compile_detects_repeated_sequences(tmp_path: Path) -> None:
    log_path = tmp_path / "guardrails_actions.jsonl"
    out_path = tmp_path / "shortcuts.json"
    now = "2026-04-09T10:00:00+00:00"
    rows = []
    for i in range(3):
        rows.append({"timestamp": now, "tool": "browser.open", "args": {"url": "https://example.com"}, "status": "ok"})
        rows.append({"timestamp": now, "tool": "browser.screenshot", "args": {"path": "assets/x.png"}, "status": "ok"})
    _write_log(log_path, rows)

    c = PatternShortcutCompiler(log_path=str(log_path), output_path=str(out_path))
    payload = c.compile(lookback_days=7, min_repeats=3, max_sequence_len=2, top_k=5)

    assert payload["shortcuts"]
    first = payload["shortcuts"][0]
    assert first["invocations"] >= 3
    assert len(first["steps"]) == 2


def test_run_shortcut_executes_steps(tmp_path: Path) -> None:
    out_path = tmp_path / "shortcuts.json"
    out_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-04-09T10:00:00+00:00",
                "shortcuts": [
                    {
                        "name": "sc_demo",
                        "invocations": 4,
                        "steps": [
                            {"tool": "a.tool", "args": {"x": 1}},
                            {"tool": "b.tool", "args": {"y": 2}},
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    class _DummyDispatcher:
        def __init__(self) -> None:
            self.calls = []

        def execute(self, tool_call, dry_run=False):  # noqa: ANN001
            self.calls.append((tool_call.tool, tool_call.args, dry_run))
            return {"status": "ok", "tool": tool_call.tool}

    d = _DummyDispatcher()
    c = PatternShortcutCompiler(log_path=str(tmp_path / "missing.jsonl"), output_path=str(out_path))
    result = c.run_shortcut(name="sc_demo", dispatcher=d, dry_run=True)

    assert result["status"] == "ok"
    assert len(d.calls) == 2
    assert d.calls[0][0] == "a.tool"
