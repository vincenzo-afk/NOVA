"""Unified LLM interface with streaming and cloud->ollama fallback."""

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
        timeout: int = 90,
    ):
        self.openai_base_url = openai_base_url.rstrip("/")
        self.ollama_base_url = ollama_base_url.rstrip("/")
        self.ollama_model = ollama_model
        self.timeout = timeout
        self.pool = RoundRobinPool(openai_keys)
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
            json={"model": "gpt-oss-120b", "messages": messages, "stream": True},
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
            data = json.loads(payload)
            token = data.get("choices", [{}])[0].get("delta", {}).get("content", "")
            if token:
                yield token

    def _ollama_stream(self, messages: list[dict], system: str) -> Iterable[str]:
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
            data = json.loads(raw_line)
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
