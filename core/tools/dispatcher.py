"""Tool dispatcher with schema prompt injection and validation.

Fixes applied:
- Bug 2 (try_parse_tool_call): Strip markdown code fences (```json...```) before JSON parsing.
- Perf 3 (rate limiter): _consume_token now raises RateLimitedError instead of blocking with
  time.sleep(), so callers on the main thread are not frozen.
"""

from __future__ import annotations

import json
import re
import time
import threading
import inspect
from typing import Any, Callable

from pydantic import BaseModel, ValidationError

from safety.guardrails import guardrails


class RateLimitedError(RuntimeError):
    """Raised when the dispatcher rate limit is exceeded (non-blocking)."""


class ToolCall(BaseModel):
    tool: str
    args: dict[str, Any]


_FENCE_RE = re.compile(r"^```(?:json)?\s*\n?(.*?)\n?```$", re.DOTALL | re.IGNORECASE)
_SENSITIVE_KEYS = {"api_key", "token", "password", "secret", "access_key", "private_key", "auth_token", "bearer_token", "api_secret"}


def _scrub_args_for_error(args: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in args.items():
        if key.lower() in _SENSITIVE_KEYS:
            out[key] = "***REDACTED***"
        elif isinstance(value, dict):
            out[key] = _scrub_args_for_error(value)
        else:
            out[key] = value
    return out


class Dispatcher:
    def __init__(self, rate_limit_rpm: int = 120):
        self.registry: dict[str, Callable[..., Any]] = {}
        self.schemas: dict[str, type[BaseModel]] = {}
        self.descriptions: dict[str, str] = {}

        # Fix Perf 3 & Bug 10: Token bucket for rate limiting tool executions with Lock
        self._max_tokens = max(0, int(rate_limit_rpm))
        self._tokens = float(self._max_tokens)
        self._last_refill = time.time()
        self._refill_rate = self._max_tokens / 60.0 if self._max_tokens > 0 else 0.0
        self._token_lock = threading.RLock()

    def _consume_token(self) -> None:
        """Consume one rate-limit token; raise RateLimitedError (non-blocking) if exhausted."""
        if self._max_tokens <= 0:
            return  # No limit configured
            
        with self._token_lock:
            now = time.time()
            elapsed = now - self._last_refill
            self._tokens = min(self._max_tokens, self._tokens + elapsed * self._refill_rate)
            self._last_refill = now

            if self._tokens < 1.0:
                # Non-blocking: raise an error instead of sleeping on the main thread
                raise RateLimitedError(
                    f"Dispatcher rate limit hit ({self._max_tokens} rpm). Retry in a moment."
                )
            self._tokens -= 1.0

    def register(
        self,
        name: str,
        fn: Callable[..., Any],
        schema: type[BaseModel],
        description: str | None = None,
    ) -> None:
        self._validate_registration_signature(name=name, fn=fn, schema=schema)
        self.registry[name] = fn
        self.schemas[name] = schema
        if description:
            self.descriptions[name] = description

    @staticmethod
    def _validate_registration_signature(
        name: str,
        fn: Callable[..., Any],
        schema: type[BaseModel],
    ) -> None:
        """Fail fast if a tool schema can't be passed to the registered function."""
        try:
            signature = inspect.signature(fn)
        except (TypeError, ValueError):
            # Builtins/callables without inspectable signatures are accepted.
            return
        kwargs = {field_name: None for field_name in schema.model_fields.keys()}
        try:
            signature.bind(**kwargs)
        except TypeError as exc:
            raise TypeError(
                f"Tool registration failed for '{name}': function signature does not "
                f"match schema fields {sorted(kwargs.keys())}. {exc}"
            ) from exc

    def get_tool_schema_prompt(self) -> str:
        tools = [
            {
                "tool": name,
                "args": model.model_json_schema(),
                **({"description": self.descriptions.get(name)} if self.descriptions.get(name) else {}),
            }
            for name, model in self.schemas.items()
        ]
        return (
            'To use a tool, output ONLY valid JSON in this exact format:\n'
            '{"tool": "<tool_name>", "args": {...}}\n\n'
            f"Available tools:\n{json.dumps(tools, indent=2)}\n\n"
            "For regular responses, output plain text. Never mix JSON and text in one response."
        )

    def try_parse_tool_call(self, raw_text: str) -> ToolCall | None:
        """Parse a tool call from LLM output.

        Fix Bug 2: Strip markdown code fences (```json ... ```) before attempting JSON parsing.
        LLMs frequently wrap JSON in markdown blocks; without stripping, all such responses
        silently lose the tool call.
        """
        text = raw_text.strip()

        # Strip markdown fences if present
        fence_match = _FENCE_RE.match(text)
        if fence_match:
            text = fence_match.group(1).strip()

        if not text.startswith("{"):
            return None
        try:
            payload = json.loads(text)
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
        _skip_guardrails: bool = False,
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
                "details": {
                    "errors": [
                        {"loc": e.get("loc"), "msg": e.get("msg"), "type": e.get("type")}
                        for e in json.loads(exc.json())
                    ],
                    "args": _scrub_args_for_error(dict(tool_call.args)),
                },
            }

        # Safety fix: dry_run must never execute real tool functions, even when
        # callers bypass guardrails (_skip_guardrails=True).
        if dry_run:
            return {
                "status": "dry_run",
                "tool": tool_call.tool,
                "args": validated.model_dump(),
            }

        # Default auth for bypass scenarios
        from safety.guardrails import RiskResult
        auth = RiskResult(blocked=False, reason="guard_bypass", score=0, level="low", plan="")
        if _skip_guardrails:
            # Keep risk scoring for audit trail integrity even when execution bypasses confirmation.
            risk = guardrails.check(tool_call)
            auth = RiskResult(
                blocked=False,
                reason="guard_bypass",
                score=risk.score,
                level=risk.level,
                plan=risk.plan,
                requires_confirmation=risk.requires_confirmation,
                auto_confirm_seconds=risk.auto_confirm_seconds,
            )

        if not _skip_guardrails:
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

        # Fix Perf 3: Non-blocking rate limit — raise instead of sleeping
        try:
            self._consume_token()
        except RateLimitedError as exc:
            result = {"status": "rate_limited", "reason": str(exc)}
            guardrails.log(tool_call, auth, result=result, status="rate_limited", confirmed_by="system")
            return result

        try:
            result = fn(**validated.model_dump())
        except TypeError as exc:
            return {
                "error": "tool_signature_error",
                "tool": tool_call.tool,
                "details": str(exc),
            }
        guardrails.log(tool_call, auth, result=result, status="ok", confirmed_by="user")
        return {"status": "ok", "tool": tool_call.tool, "result": result, "risk": auth.score}
