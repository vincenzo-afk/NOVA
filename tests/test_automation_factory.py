from __future__ import annotations

import json
from pathlib import Path

from tasks.automation_factory import AutomationFactory


def _factory(tmp_path: Path) -> AutomationFactory:
    return AutomationFactory(
        plugin_generate_fn=lambda prompt: {"status": "ok", "prompt_len": len(prompt)},
        schedule_every_fn=lambda name, schedule, goal: {
            "status": "ok",
            "mission": {"name": name, "schedule": schedule, "goal": goal},
        },
        notify_tts_fn=lambda _text: True,
        vision_analyze_fn=lambda _img: {"scene_type": "error_dialog", "detected_errors": ["button_missing"]},
        record_event_fn=lambda _k, _m: None,
        queue_path=str(tmp_path / "jobs.json"),
        plugin_dir=str(tmp_path / "plugins"),
    )


def test_live_feed_builder_returns_plugin_and_mission(tmp_path: Path, monkeypatch) -> None:
    f = _factory(tmp_path)
    monkeypatch.setattr(
        f,
        "_collect_docs",
        lambda query, max_sources=3: {
            "query": query,
            "sources": [{"title": "Doc", "url": "https://example.com"}],
            "summary": "endpoint: /scores",
        },
    )
    result = f.live_data_feed_builder("cricket", interval_minutes=5)
    assert result["status"] == "ok"
    assert result["plugin"]["status"] == "ok"
    assert result["mission"]["status"] == "ok"


def test_batch_queue_persists_and_has_status(tmp_path: Path) -> None:
    f = _factory(tmp_path)
    queued = f.enqueue_batch_api_plugins(["IRCTC", "GitHub"])
    assert queued["status"] == "ok"
    assert queued["queued"] == 2
    status = f.batch_status()
    assert status["count"] >= 2
    assert (tmp_path / "jobs.json").exists()


def test_failure_recovery_triggers_on_second_failure(tmp_path: Path) -> None:
    img = tmp_path / "screen.png"
    img.write_bytes(b"fake")
    f = _factory(tmp_path)
    first = f.record_failure_and_recover("browser.click", str(img))
    second = f.record_failure_and_recover("browser.click", str(img))
    assert first["recovery_triggered"] is False
    assert second["recovery_triggered"] is True
    assert second["plugin"]["status"] == "ok"


def test_skill_learner_writes_named_control_plugin(tmp_path: Path, monkeypatch) -> None:
    f = _factory(tmp_path)
    monkeypatch.setattr(
        f,
        "_collect_docs",
        lambda query, max_sources=3: {"query": query, "sources": [], "summary": "Figma docs sample"},
    )
    result = f.learn_skill("Figma")
    assert result["status"] == "ok"
    assert result["scaffold_path"].endswith("figma_control.py")
    assert Path(result["scaffold_path"]).exists()


def test_smart_home_stub_creation(tmp_path: Path, monkeypatch) -> None:
    f = _factory(tmp_path)
    monkeypatch.setattr(
        f,
        "_scan_lan_devices",
        lambda: {"status": "ok", "devices": [{"ip": "1.1.1.1", "mac": "00:17:88:aa:bb:cc", "vendor_hint": "Philips"}]},
    )
    out = f.smart_home_discoverer()
    assert out["status"] == "ok"
    assert any("bulb_control.py" in p for p in out["stubs"])
    created = Path(out["stubs"][0])
    assert created.exists()
    created.unlink(missing_ok=True)
