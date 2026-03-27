"""Tool dispatcher with schema prompt injection and validation."""

from __future__ import annotations

import json
import time
from typing import Any, Callable

from pydantic import BaseModel, ValidationError

from safety.guardrails import guardrails


class ToolCall(BaseModel):
    tool: str
    args: dict[str, Any]


class Dispatcher:
    def __init__(self, rate_limit_rpm: int = 120):
        self.registry: dict[str, Callable[..., Any]] = {}
        self.schemas: dict[str, type[BaseModel]] = {}
        
        # Fix 1.7: Token bucket for rate limiting tool executions
        self._max_tokens = rate_limit_rpm
        self._tokens = float(rate_limit_rpm)
        self._last_refill = time.time()
        self._refill_rate = rate_limit_rpm / 60.0

    def _consume_token(self) -> None:
        """Fix 1.7: Consume a token, sleeping if necessary to enforce rate limit."""
        if self._max_tokens <= 0:
            return  # No limit
        now = time.time()
        elapsed = now - self._last_refill
        self._tokens = min(self._max_tokens, self._tokens + elapsed * self._refill_rate)
        self._last_refill = now
        
        if self._tokens < 1.0:
            sleep_time = (1.0 - self._tokens) / self._refill_rate
            time.sleep(sleep_time)
            self._tokens = 0.0
            self._last_refill = time.time()
        else:
            self._tokens -= 1.0

    def register(self, name: str, fn: Callable[..., Any], schema: type[BaseModel]) -> None:
        self.registry[name] = fn
        self.schemas[name] = schema

    def get_tool_schema_prompt(self) -> str:
        tools = [
            {"tool": name, "args": model.model_json_schema()}
            for name, model in self.schemas.items()
        ]
        return (
            'To use a tool, output ONLY valid JSON in this exact format:\n'
            '{"tool": "<tool_name>", "args": {...}}\n\n'
            f"Available tools:\n{json.dumps(tools, indent=2)}\n\n"
            "For regular responses, output plain text. Never mix JSON and text in one response."
        )

    def try_parse_tool_call(self, raw_text: str) -> ToolCall | None:
        raw_text = raw_text.strip()
        if not raw_text.startswith("{"):
            return None
        try:
            payload = json.loads(raw_text)
        except json.JSONDecodeError:
            return None
        try:
            return ToolCall.model_validate(payload)
        except ValidationError:
            return None

    def execute(
        self,
        tool_call: ToolCall,
        confirm_callback: Callable[[str], bool] | None = None,
        announce_callback: Callable[[str], None] | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        fn = self.registry.get(tool_call.tool)
        schema = self.schemas.get(tool_call.tool)
        if not fn or not schema:
            return {"error": f"unknown tool: {tool_call.tool}"}

        try:
            validated = schema.model_validate(tool_call.args)
        except ValidationError as exc:
            return {
                "error": "validation_error",
                "tool": tool_call.tool,
                "details": json.loads(exc.json()),
            }

        risk = guardrails.check(tool_call)
        auth = guardrails.authorize(
            tool_call=tool_call,
            risk=risk,
            confirm_callback=confirm_callback,
            announce_callback=announce_callback,
            dry_run=dry_run,
            sleep_fn=time.sleep,
        )
        if auth.blocked:
            status = "cancelled" if auth.reason == "user_declined" else "blocked"
            result = {"status": status, "reason": auth.reason, "risk": auth.score}
            guardrails.log(tool_call, auth, result=result, status=status, confirmed_by="user")
            return result

        if dry_run:
            result = {
                "status": "dry_run",
                "risk": auth.score,
                "level": auth.level,
                "plan": auth.plan,
            }
            guardrails.log(tool_call, auth, result=result, status="dry_run", confirmed_by="system")
            return result

        # Fix 1.7: Consume token before execution to enforce rate limit
        self._consume_token()

        result = fn(**validated.model_dump())
        guardrails.log(tool_call, auth, result=result, status="ok", confirmed_by="user")
        return {"status": "ok", "tool": tool_call.tool, "result": result, "risk": auth.score}
