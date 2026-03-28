"""Unit tests for Dispatcher.

Covers:
- Markdown fence stripping in try_parse_tool_call (Bug 2 fix)
- Non-blocking rate limiter (Perf 3 fix)
- Tool registration and execution
- Unknown-tool handling
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from core.tools.dispatcher import Dispatcher, ToolCall, RateLimitedError


class _EchoArgs(BaseModel):
    message: str


def _echo(message: str) -> str:
    return f"echo: {message}"


# ---------------------------------------------------------------------------
# try_parse_tool_call — markdown fence stripping
# ---------------------------------------------------------------------------

def test_parse_plain_json():
    d = Dispatcher()
    d.register("test.echo", _echo, _EchoArgs)
    tc = d.try_parse_tool_call('{"tool": "test.echo", "args": {"message": "hi"}}')
    assert tc is not None
    assert tc.tool == "test.echo"


def test_parse_json_in_backtick_fence():
    """Bug 2 fix: LLMs often wrap JSON in ```json fences; these must be stripped."""
    d = Dispatcher()
    raw = '```json\n{"tool": "test.echo", "args": {"message": "hi"}}\n```'
    tc = d.try_parse_tool_call(raw)
    assert tc is not None
    assert tc.tool == "test.echo"


def test_parse_json_in_plain_fence():
    d = Dispatcher()
    raw = '```\n{"tool": "test.echo", "args": {"message": "world"}}\n```'
    tc = d.try_parse_tool_call(raw)
    assert tc is not None


def test_parse_plain_text_returns_none():
    d = Dispatcher()
    assert d.try_parse_tool_call("Hello, how can I help?") is None


def test_parse_empty_returns_none():
    d = Dispatcher()
    assert d.try_parse_tool_call("") is None


# ---------------------------------------------------------------------------
# execute — basic dispatching
# ---------------------------------------------------------------------------

def test_execute_registered_tool(monkeypatch):
    d = Dispatcher(rate_limit_rpm=0)  # no rate limit
    d.register("test.echo", _echo, _EchoArgs)

    # Bypass guardrails for unit test
    from safety.guardrails import RiskResult
    monkeypatch.setattr("safety.guardrails.guardrails.check", lambda _: RiskResult(score=0, level="low"))
    monkeypatch.setattr(
        "safety.guardrails.guardrails.authorize",
        lambda tool_call, risk, **kw: risk,
    )
    monkeypatch.setattr("safety.guardrails.guardrails.log", lambda *a, **kw: None)

    result = d.execute(ToolCall(tool="test.echo", args={"message": "hello"}))
    assert result["status"] == "ok"
    assert result["result"] == "echo: hello"


def test_execute_unknown_tool():
    d = Dispatcher()
    result = d.execute(ToolCall(tool="nonexistent.tool", args={}))
    assert "error" in result
    assert "unknown tool" in result["error"]


def test_execute_validation_error(monkeypatch):
    d = Dispatcher(rate_limit_rpm=0)
    d.register("test.echo", _echo, _EchoArgs)
    result = d.execute(ToolCall(tool="test.echo", args={"wrong_field": 123}))
    assert result.get("error") == "validation_error"


# ---------------------------------------------------------------------------
# Rate limiter — non-blocking (Perf 3 fix)
# ---------------------------------------------------------------------------

def test_rate_limiter_raises_not_sleeps():
    """Perf 3 fix: rate limit must raise RateLimitedError, not block with time.sleep."""
    d = Dispatcher(rate_limit_rpm=1)
    # Drain the solitary token
    d._tokens = 0.0
    with pytest.raises(RateLimitedError):
        d._consume_token()


def test_rate_limiter_execute_returns_rate_limited(monkeypatch):
    from safety.guardrails import RiskResult
    monkeypatch.setattr("safety.guardrails.guardrails.check", lambda _: RiskResult(score=0, level="low"))
    monkeypatch.setattr(
        "safety.guardrails.guardrails.authorize",
        lambda tool_call, risk, **kw: risk,
    )
    monkeypatch.setattr("safety.guardrails.guardrails.log", lambda *a, **kw: None)

    d = Dispatcher(rate_limit_rpm=1)
    d.register("test.echo", _echo, _EchoArgs)
    d._tokens = 0.0  # force rate limit

    result = d.execute(ToolCall(tool="test.echo", args={"message": "x"}))
    assert result["status"] == "rate_limited"
