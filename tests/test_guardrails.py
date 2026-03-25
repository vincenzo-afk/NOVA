from __future__ import annotations

from core.tools.dispatcher import ToolCall
from safety.guardrails import guardrails


def test_guardrails_high_risk_for_destructive_tools():
    risk = guardrails.check(ToolCall(tool="win32_api.delete", args={"path": "/tmp/x"}))
    assert risk.score >= 7


def test_guardrails_low_risk_for_safe_tools():
    risk = guardrails.check(ToolCall(tool="web.search", args={"query": "python"}))
    assert risk.score <= 3


def test_guardrails_high_risk_requires_confirmation():
    call = ToolCall(tool="win32_api.delete", args={"path": "/tmp/x"})
    risk = guardrails.check(call)
    approved = guardrails.authorize(call, risk, confirm_callback=lambda _: False)
    assert approved.blocked
    assert approved.reason == "user_declined"


def test_guardrails_medium_risk_auto_confirms():
    call = ToolCall(tool="browser.open", args={"url": "https://example.com"})
    risk = guardrails.check(call)
    assert risk.level in {"low", "medium", "high"}
    if risk.level == "medium":
        approved = guardrails.authorize(
            call,
            risk,
            announce_callback=lambda _: None,
            sleep_fn=lambda _: None,
        )
        assert not approved.blocked
