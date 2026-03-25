from __future__ import annotations

from pydantic import BaseModel

from core.tools.dispatcher import Dispatcher, ToolCall


class SumArgs(BaseModel):
    a: int
    b: int


def add(a: int, b: int) -> int:
    return a + b


def test_dispatcher_schema_prompt_and_execution():
    d = Dispatcher()
    d.register("math.add", add, SumArgs)

    prompt = d.get_tool_schema_prompt()
    assert "math.add" in prompt

    call = ToolCall(tool="math.add", args={"a": 2, "b": 3})
    result = d.execute(call)
    assert result["status"] == "ok"
    assert result["result"] == 5


def test_dispatcher_validation_error_shape():
    d = Dispatcher()
    d.register("math.add", add, SumArgs)
    call = ToolCall(tool="math.add", args={"a": 2})
    result = d.execute(call)
    assert result["error"] == "validation_error"


def test_dispatcher_dry_run_does_not_execute_function():
    d = Dispatcher()
    ran = {"value": False}

    def _dangerous(a: int, b: int) -> int:
        ran["value"] = True
        return a + b

    d.register("win32_api.delete", _dangerous, SumArgs)
    call = ToolCall(tool="win32_api.delete", args={"a": 1, "b": 2})
    result = d.execute(call, dry_run=True)
    assert result["status"] == "dry_run"
    assert not ran["value"]


def test_dispatcher_high_risk_respects_confirmation_callback():
    d = Dispatcher()

    def _dangerous(a: int, b: int) -> int:
        return a + b

    d.register("win32_api.delete", _dangerous, SumArgs)
    call = ToolCall(tool="win32_api.delete", args={"a": 2, "b": 3})
    result = d.execute(call, confirm_callback=lambda _: False)
    assert result["status"] in {"blocked", "cancelled"}
