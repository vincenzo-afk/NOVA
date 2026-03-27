"""Unified LLM interface with streaming, round-robin key rotation, and cloud→Ollama fallback."""

from __future__ import annotations

import json
from typing import Generator, Iterable

import requests

from core.llm.roundrobin import RoundRobinPool


class RateLimitError(RuntimeError):
    def __init__(self, retry_after: int = 60):
        super().__init__("rate_limited")
        self.retry_after = retry_after


class LLMEngine:
    def __init__(
        self,
        openai_base_url: str,
        openai_keys: list[str],
        ollama_base_url: str,
        ollama_model: str,
        openai_model: str = "gpt-4o",
        timeout: int = 90,
    ):
        self.openai_base_url = openai_base_url.rstrip("/")
        self.ollama_base_url = ollama_base_url.rstrip("/")
        self.ollama_model = ollama_model
        self.openai_model = openai_model
        self.timeout = timeout
        # Only initialise pool if we have keys; otherwise cloud path is effectively disabled
        self.pool: RoundRobinPool | None = None
        if openai_keys:
            try:
                self.pool = RoundRobinPool(openai_keys)
            except ValueError:
                self.pool = None
        self.last_provider = "unknown"

    def ask(self, prompt: str, system: str, history: list[dict] | None = None) -> str:
        return "".join(self.ask_stream(prompt, system, history))

    def ask_stream(
        self,
        prompt: str,
        system: str,
        history: list[dict] | None = None,
    ) -> Generator[str, None, None]:
        messages = self._build_messages(prompt=prompt, system=system, history=history or [])

        # Attempt cloud keys if pool is available
        if self.pool is not None:
            tried: set[str] = set()
            while True:
                key = self.pool.get_next()
                if not key or key in tried:
                    break
                tried.add(key)
                self.last_provider = f"cloud • {self.pool.key_label(key)}"
                try:
                    for token in self._cloud_stream(messages=messages, api_key=key):
                        yield token
                    self.pool.mark_success(key)
                    return
                except RateLimitError as exc:
                    self.pool.mark_rate_limited(key, retry_after=exc.retry_after)
                except requests.RequestException:
                    self.pool.mark_rate_limited(key, retry_after=60)
                except Exception:
                    self.pool.mark_dead(key)

        # Fallback to Ollama
        self.last_provider = "local • ollama"
        try:
            for token in self._ollama_stream(messages=messages, system=system):
                yield token
        except Exception as exc:
            yield f"[ERROR] Fallback LLM failed: {exc}"

    def _build_messages(self, prompt: str, system: str, history: list[dict]) -> list[dict]:
        msgs = [{"role": "system", "content": system}]
        for item in history:
            role = item.get("role")
            content = item.get("content")
            if role in {"user", "assistant", "system"} and content:
                msgs.append({"role": role, "content": content})
        msgs.append({"role": "user", "content": prompt})
        return msgs

    def _cloud_stream(self, messages: list[dict], api_key: str) -> Iterable[str]:
        response = requests.post(
            f"{self.openai_base_url}/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={"model": self.openai_model, "messages": messages, "stream": True},
            timeout=self.timeout,
            stream=True,
        )

        if response.status_code == 429:
            retry_after = int(response.headers.get("Retry-After", "60"))
            raise RateLimitError(retry_after=retry_after)
        response.raise_for_status()

        for raw_line in response.iter_lines(decode_unicode=True):
            if not raw_line or not raw_line.startswith("data:"):
                continue
            payload = raw_line[5:].strip()
            if payload == "[DONE]":
                break
            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                continue
            token = data.get("choices", [{}])[0].get("delta", {}).get("content", "")
            if token:
                yield token

    def _ollama_stream(self, messages: list[dict], system: str) -> Iterable[str]:
        """Use Ollama's /api/chat endpoint for better multi-turn support."""
        response = requests.post(
            f"{self.ollama_base_url}/api/chat",
            json={
                "model": self.ollama_model,
                "messages": messages,
                "stream": True,
            },
            timeout=self.timeout,
            stream=True,
        )
        if response.status_code == 404:
            # Older Ollama versions only have /api/generate — fall back
            yield from self._ollama_generate_stream(messages, system)
            return
        response.raise_for_status()

        for raw_line in response.iter_lines(decode_unicode=True):
            if not raw_line:
                continue
            try:
                data = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            token = data.get("message", {}).get("content", "")
            if token:
                yield token
            if data.get("done"):
                break

    def _ollama_generate_stream(self, messages: list[dict], system: str) -> Iterable[str]:
        """Legacy Ollama /api/generate endpoint fallback."""
        prompt = self._messages_to_prompt(messages)
        response = requests.post(
            f"{self.ollama_base_url}/api/generate",
            json={
                "model": self.ollama_model,
                "prompt": prompt,
                "system": system,
                "stream": True,
            },
            timeout=self.timeout,
            stream=True,
        )
        response.raise_for_status()

        for raw_line in response.iter_lines(decode_unicode=True):
            if not raw_line:
                continue
            try:
                data = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            token = data.get("response", "")
            if token:
                yield token
            if data.get("done"):
                break

    @staticmethod
    def _messages_to_prompt(messages: list[dict]) -> str:
        lines = []
        for m in messages:
            lines.append(f"[{m['role']}] {m['content']}")
        return "\n".join(lines)
