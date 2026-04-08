from __future__ import annotations

from core.a2a.conflict_resolver import ConflictResolver
from core.a2a.peer_registry import PeerRegistry
from core.a2a.shared_memory_bus import SharedMemoryBus
from core.think.nudge_engine import NudgeEngine
from core.think.self_evaluator import SelfEvaluator
from tasks.missions import MissionManager


class _DummyScheduler:
    def __init__(self):
        self.added: dict[str, dict] = {}
        self.removed: list[str] = []

    def add_from_text(self, fn, schedule_text: str, job_id: str):
        self.added[job_id] = {"fn": fn, "schedule_text": schedule_text}
        return {"schedule_text": schedule_text}

    def remove_job(self, job_id: str) -> bool:
        self.removed.append(job_id)
        self.added.pop(job_id, None)
        return True


def test_self_evaluator_gates_and_persists(tmp_path):
    ratings_path = tmp_path / "ratings.jsonl"
    evaluator = SelfEvaluator(
        llm_ask_fn=lambda _prompt, _system: (
            '{"relevance": 9, "actionability": 8, "conciseness": 7, "note": "Good answer"}'
        ),
        persist_path=ratings_path,
    )

    assert evaluator.should_rate(
        assistant_text="a" * 400,
        estimated_tokens=80,
        daily_total_tokens=100,
        daily_alert_threshold=1000,
        enabled=True,
        min_response_tokens=50,
        skip_usage_pct=90,
    )
    assert not evaluator.should_rate(
        assistant_text="short",
        estimated_tokens=10,
        daily_total_tokens=100,
        daily_alert_threshold=1000,
        enabled=True,
        min_response_tokens=50,
        skip_usage_pct=90,
    )

    payload = evaluator.evaluate(prompt="How to test?", response="Use pytest.", session_id="sess-abc")
    assert payload["ratings"]["relevance"] == 9
    assert ratings_path.exists()
    avg = evaluator.weekly_averages(session_prefix="sess-")
    assert avg["relevance"] == 9.0


def test_nudge_engine_thresholds_and_mute():
    exports: list[str] = []
    engine = NudgeEngine(export_callback=lambda: exports.append("exported"))
    base = 1.0
    engine.update_context(task_key="coding:editor", now_ts=base)

    msg_2h, insistent_2h = engine.maybe_nudge(now_ts=base + (2 * 3600) + 1)
    assert msg_2h
    assert insistent_2h is False
    assert len(exports) == 1

    msg_4h, insistent_4h = engine.maybe_nudge(now_ts=base + (4 * 3600) + 1)
    assert msg_4h
    assert insistent_4h is True
    assert len(exports) == 2

    engine.mute_today()
    muted_msg, muted_insistent = engine.maybe_nudge(now_ts=base + (6 * 3600) + 1)
    assert muted_msg == ""
    assert muted_insistent is False


def test_mission_manager_parse_schedule_and_run(tmp_path):
    scheduler = _DummyScheduler()
    enqueued: list[str] = []
    manager = MissionManager(
        scheduler=scheduler,
        enqueue_goal_fn=lambda goal: enqueued.append(goal) or {"status": "queued", "goal": goal},
        persist_path=tmp_path / "missions.json",
    )

    result = manager.parse_and_add_from_text(
        "schedule mission morning_brief every day at 08:00 to summarize overnight updates"
    )
    assert result["status"] == "ok"
    assert "mission_morning_brief" in scheduler.added

    run_now = manager.run_mission_now("morning_brief")
    assert run_now["status"] == "ok"
    assert enqueued and "overnight updates" in enqueued[-1]

    disable = manager.enable_mission("morning_brief", False)
    assert disable["status"] == "ok"
    assert disable["mission"]["enabled"] is False
    assert "mission_morning_brief" in scheduler.removed


def test_shared_memory_bus_reads_broadcast_and_target_messages(tmp_path):
    bus = SharedMemoryBus(path=tmp_path / "shared_bus.jsonl")
    bus.publish(
        from_agent="nova-a",
        to_agent="broadcast",
        msg_type="status_update",
        payload={"ok": True},
    )
    bus.publish(
        from_agent="nova-b",
        to_agent="nova-a",
        msg_type="context_sync",
        payload={"digest": "abc"},
    )
    rows = bus.read(to_agent="nova-a", limit=10, include_broadcast=True)
    assert len(rows) == 2
    assert {row.get("msg_type") for row in rows} == {"status_update", "context_sync"}


def test_conflict_resolver_picks_deterministic_winner(tmp_path):
    resolver = ConflictResolver(lock_path=tmp_path / "locks.json")
    claim_1 = resolver.claim_file(agent_name="zeta", filepath="main.py")
    assert claim_1["status"] == "claimed"

    claim_2 = resolver.claim_file(agent_name="alpha", filepath="main.py")
    assert claim_2["status"] == "conflict"
    assert claim_2["winner"] == "alpha"
    assert claim_2["paused_agent"] == "zeta"


def test_peer_registry_upsert_and_mdns_discovery_graceful(tmp_path, monkeypatch):
    monkeypatch.setattr(PeerRegistry, "_advertise_self", lambda self, record: None)
    registry = PeerRegistry(path=tmp_path / "peers.json")
    rec = registry.upsert_self(
        agent_name="nova-a",
        session="work",
        tools=["doc.query", "web.search"],
        capabilities_hash="abc123",
        health_port=8765,
    )
    assert rec["agent_name"] == "nova-a"
    listed = registry.list_peers()
    assert listed and listed[0]["agent_name"] == "nova-a"
    mdns = registry.discover_mdns_peers(timeout_seconds=0.1)
    assert isinstance(mdns, list)
    registry.close()
