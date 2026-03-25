from __future__ import annotations

import requests

from core.llm.engine import LLMEngine


class StubEngine(LLMEngine):
    def __init__(self, cloud_ok: bool):
        super().__init__(
            openai_base_url="https://example.com",
            openai_keys=["k1", "k2"],
            ollama_base_url="http://localhost:11434",
            ollama_model="llama3",
        )
        self.cloud_ok = cloud_ok

    def _cloud_stream(self, messages, api_key):
        if not self.cloud_ok:
            raise requests.RequestException("boom")
        yield "cloud"

    def _ollama_stream(self, messages, system):
        yield "local"


def test_cloud_path_selected_when_available():
    engine = StubEngine(cloud_ok=True)
    out = "".join(engine.ask_stream("hello", "system", []))
    assert out == "cloud"
    assert engine.last_provider.startswith("cloud")


def test_fallback_to_ollama_when_cloud_fails():
    engine = StubEngine(cloud_ok=False)
    out = "".join(engine.ask_stream("hello", "system", []))
    assert out == "local"
    assert engine.last_provider == "local • ollama"
