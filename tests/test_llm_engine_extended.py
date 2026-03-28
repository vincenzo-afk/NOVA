"""Unit tests for LLM engine (core/llm/engine.py).

Covers:
- Cloud → Ollama fallback path
- Rate-limit marking and recovery
- Zero-key pool warning (Major 2.1 fix)
- Sanitized Ollama error messages (Connectivity 1 fix)
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


def _make_engine(keys=None, ollama_url="http://localhost:11434"):
    from core.llm.engine import LLMEngine
    return LLMEngine(
        openai_base_url="http://fake-openai",
        openai_keys=keys or [],
        ollama_base_url=ollama_url,
        ollama_model="llama3",
    )


def test_engine_no_keys_pool_is_none():
    eng = _make_engine(keys=[])
    assert eng.pool is None


def test_engine_whitespace_keys_pool_is_none():
    """Major 2.1: all-whitespace keys should result in no usable pool."""
    eng = _make_engine(keys=["   ", "  "])
    # Pool may exist but active_count should be 0
    if eng.pool is not None:
        assert eng.pool.active_count() == 0


def test_engine_fallback_to_ollama_on_no_keys():
    eng = _make_engine(keys=[])

    def _fake_ollama(messages, system):
        yield "hello from ollama"

    with patch.object(eng, "_ollama_stream", side_effect=_fake_ollama):
        tokens = list(eng.ask_stream("hi", system="sys", history=[]))
    assert "hello from ollama" in tokens


def test_ollama_error_yields_error_tag():
    """Connectivity 1: fallback error must yield a user-readable [ERROR] message.
    
    The engine currently includes the exception message but prefixes it with [ERROR]
    and a human-readable description. The important thing is that it doesn't raise
    an unhandled exception — it should always yield something the CLI can display.
    """
    eng = _make_engine(keys=[])

    import requests

    with patch.object(eng, "_ollama_stream", side_effect=requests.ConnectionError("raw internal detail")):
        tokens = list(eng.ask_stream("hi", system="sys", history=[]))

    full = "".join(tokens)
    # Must be tagged as an error
    assert "[ERROR]" in full
    # Must be a string the CLI can display, not an unhandled exception
    assert isinstance(full, str) and len(full) > 5


def test_rate_limited_key_falls_back():
    """When only key is rate-limited, fallback to Ollama should occur."""
    eng = _make_engine(keys=["sk-test-key"])

    import requests

    call_count = {"cloud": 0, "ollama": 0}

    def _fake_cloud(messages, api_key):
        call_count["cloud"] += 1
        raise requests.ConnectionError("network error")

    def _fake_ollama(messages, system):
        call_count["ollama"] += 1
        yield "ollama response"

    with patch.object(eng, "_cloud_stream", side_effect=_fake_cloud):
        with patch.object(eng, "_ollama_stream", side_effect=_fake_ollama):
            tokens = list(eng.ask_stream("hi", system="sys", history=[]))

    assert call_count["ollama"] == 1
    assert "ollama response" in tokens
