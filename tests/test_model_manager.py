from __future__ import annotations

from core.llm.roundrobin import RoundRobinPool
from interfaces.model_manager import (
    add_runtime_key,
    provider_key_snapshot,
    recommend_provider,
    remove_runtime_key,
)


class _DummyProfiler:
    @staticmethod
    def all_stats():
        return {
            "web.search": {
                "success": 9,
                "failure": 1,
                "avg_latency_ms": 320.0,
            }
        }


class _DummyEngine:
    def __init__(self, keys: list[str]):
        self.pool = RoundRobinPool(keys)

    def provider_snapshot(self):
        return self.pool.snapshot()


class _DummyAgent:
    def __init__(self, keys: list[str]):
        self.engine = _DummyEngine(keys)
        self._tool_profiler = _DummyProfiler()


def test_provider_key_snapshot_normalizes_pool_rows():
    agent = _DummyAgent(["k1", "k2"])
    snap = provider_key_snapshot(agent)
    assert "cloud" in snap
    assert snap["active_count"] == 2
    assert snap["status_counts"]["active"] == 2


def test_recommend_provider_penalizes_cloud_when_no_active_keys():
    class _NoCloudAgent:
        class _Engine:
            @staticmethod
            def provider_snapshot():
                return {"cloud": [], "active_count": 0}

        engine = _Engine()
        _tool_profiler = _DummyProfiler()

    rows = [
        {"provider": "local_ollama", "ok": True, "latency_s": 0.9},
        {"provider": "cloud • key_1", "ok": True, "latency_s": 0.4},
    ]
    rec = recommend_provider(_NoCloudAgent(), benchmark_rows=rows)
    assert rec["recommended"] == "local_ollama"


def test_add_and_remove_runtime_key_openai_updates_pool(monkeypatch):
    from config.settings import settings

    original_openai = list(getattr(settings, "OPENAI_API_KEYS", []) or [])
    try:
        monkeypatch.setattr(settings, "OPENAI_API_KEYS", [], raising=False)
        agent = _DummyAgent([])
        added = add_runtime_key(agent, "openai", "sk-test-key-123")
        assert added["status"] == "ok"
        assert added["count"] == 1
        snap = provider_key_snapshot(agent)
        assert snap["active_count"] == 1

        removed = remove_runtime_key(agent, "openai", 1)
        assert removed["status"] == "ok"
        assert removed["count"] == 0
        snap2 = provider_key_snapshot(agent)
        assert snap2["active_count"] == 0
    finally:
        settings.OPENAI_API_KEYS = original_openai
