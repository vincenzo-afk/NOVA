from __future__ import annotations

from mcp.master_mcp import MasterMCP


def test_master_mcp_local_connect_and_call():
    mcp = MasterMCP()
    mcp.connect(
        "local_service",
        {
            "tools": [{"name": "echo"}],
            "handlers": {"echo": lambda text: {"echo": text}},
        },
    )
    assert mcp.is_connected("local_service")
    assert mcp.list_services() == ["local_service"]
    assert mcp.call_tool("local_service", "echo", text="hello") == {"echo": "hello"}


def test_master_mcp_http_discovery_and_call(monkeypatch):
    class DummyResponse:
        def __init__(self, payload, status_code: int = 200):
            self._payload = payload
            self.status_code = status_code
            self.text = str(payload)

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError("http error")

        def json(self):
            return self._payload

    def fake_request(method, url, **kwargs):
        assert method in {"get", "post"}
        if method == "get":
            assert url.endswith("/tools")
            return DummyResponse({"tools": [{"name": "ping"}]})
        assert url.endswith("/tools/ping/invoke")
        assert kwargs.get("json") == {"args": {"value": 42}}
        return DummyResponse({"ok": True, "value": 42})

    monkeypatch.setattr("mcp.master_mcp.requests.request", fake_request)

    mcp = MasterMCP()
    mcp.connect_http("remote", "http://localhost:9900", discover=True)
    tools = mcp.list_tools("remote")
    assert tools and tools[0]["name"] == "ping"
    result = mcp.call_tool("remote", "ping", value=42)
    assert result == {"ok": True, "value": 42}


def test_master_mcp_builtin_github_registers_tools():
    mcp = MasterMCP()
    mcp.connect_builtin("github", "ghp_test_key")
    names = [tool["name"] for tool in mcp.list_tools("github")]
    assert "list_open_prs" in names
    assert "get_repo" in names


def test_master_mcp_local_tool_error_is_normalized():
    mcp = MasterMCP()

    def boom():
        raise RuntimeError("bad things")

    mcp.connect("svc", {"tools": [{"name": "boom"}], "handlers": {"boom": boom}})
    result = mcp.call_tool("svc", "boom")
    assert result["ok"] is False
    assert result["error"]["code"] == "local_tool_call_failed"
    assert result["error"]["tool"] == "boom"


def test_master_mcp_http_call_retries_on_transient_failure(monkeypatch):
    class DummyResponse:
        def __init__(self, payload, status_code: int = 200):
            self._payload = payload
            self.status_code = status_code
            self.text = str(payload)

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError("http error")

        def json(self):
            return self._payload

    calls = {"count": 0}

    def fake_request(method, url, **kwargs):
        _ = (method, kwargs)
        calls["count"] += 1
        if url.endswith("/tools"):
            return DummyResponse({"tools": [{"name": "ping"}]})
        if calls["count"] == 2:
            raise RuntimeError("temporary network")
        return DummyResponse({"ok": True})

    monkeypatch.setattr("mcp.master_mcp.requests.request", fake_request)

    mcp = MasterMCP(max_retries=2, backoff_base_seconds=0, sleep_fn=lambda _: None)
    mcp.connect_http("remote", "http://localhost:9900", discover=True)
    result = mcp.call_tool("remote", "ping")
    assert result == {"ok": True}
    assert calls["count"] >= 3


def test_home_assistant_extended_tools(monkeypatch):
    class DummyResponse:
        def __init__(self, payload, status_code: int = 200):
            self._payload = payload
            self.status_code = status_code
            self.text = str(payload)
            self.ok = status_code < 400

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError("http error")

        def json(self):
            return self._payload

    def fake_request(method, url, **kwargs):
        _ = kwargs
        if method == "get" and url.endswith("/api/states"):
            return DummyResponse(
                [
                    {
                        "entity_id": "automation.morning",
                        "state": "on",
                        "attributes": {"friendly_name": "Morning"},
                    },
                    {
                        "entity_id": "light.kitchen",
                        "state": "off",
                        "attributes": {"friendly_name": "Kitchen Light"},
                    },
                ]
            )
        if method == "post" and url.endswith("/api/services/automation/trigger"):
            return DummyResponse({"done": True})
        if method == "post" and url.endswith("/api/services/climate/set_temperature"):
            return DummyResponse({"done": True})
        if method == "get" and url.endswith("/api/recorder/statistics_during_period"):
            return DummyResponse({"kwh": 12.3})
        return DummyResponse({})

    monkeypatch.setattr("mcp.master_mcp.requests.request", fake_request)

    mcp = MasterMCP()
    mcp.connect_builtin("home_assistant", "http://ha.local:8123|token-123")
    names = {tool["name"] for tool in mcp.list_tools("home_assistant")}
    assert {"list_automations", "trigger_automation", "set_climate", "get_energy_stats"} <= names

    automations = mcp.call_tool("home_assistant", "list_automations")
    assert automations and automations[0]["entity_id"] == "automation.morning"

    trig = mcp.call_tool("home_assistant", "trigger_automation", automation_id="morning")
    assert trig["ok"] is True

    temp = mcp.call_tool("home_assistant", "set_climate", entity_id="climate.hall", temperature=24.0)
    assert temp["ok"] is True

    energy = mcp.call_tool("home_assistant", "get_energy_stats", period="day")
    assert energy["ok"] is True
