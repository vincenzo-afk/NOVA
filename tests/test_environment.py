from __future__ import annotations

from core.context import environment as env


def test_snapshot_environment_returns_stale_cache_and_refreshes(monkeypatch):
    original_cache = dict(env._ENVIRONMENT_CACHE)
    original_cache_time = env._ENVIRONMENT_CACHE_TIME
    original_inflight = env._REFRESH_INFLIGHT
    try:
        env._ENVIRONMENT_CACHE = {
            "time": "2025-01-01T00:00:00",
            "cwd": "/tmp",
            "os": "x",
            "hostname": "h",
            "network": "offline",
            "clipboard": "secret",
            "foreground_app": "app",
            "window_title": "title",
            "battery_pct": None,
            "last_active_file": "/tmp/file.txt",
        }
        env._ENVIRONMENT_CACHE_TIME = 0.0
        env._REFRESH_INFLIGHT = False

        started = {"value": False}

        class _FakeThread:
            def __init__(self, target=None, args=(), daemon=None):
                self._target = target
                self._args = args

            def start(self):
                started["value"] = True
                # Simulate async launch without running heavy snapshot logic
                env._REFRESH_INFLIGHT = True

        monkeypatch.setattr(env.time, "monotonic", lambda: 1000.0)
        monkeypatch.setattr(env.threading, "Thread", _FakeThread)

        snap = env.snapshot_environment(include_clipboard=False)

        assert started["value"] is True
        assert snap["network"] == "offline"
        assert "clipboard" not in snap
        assert snap["last_active_file"] is None
    finally:
        env._ENVIRONMENT_CACHE = original_cache
        env._ENVIRONMENT_CACHE_TIME = original_cache_time
        env._REFRESH_INFLIGHT = original_inflight
