from __future__ import annotations

import base64

import voice.tts as tts


def test_extract_audio_bytes_from_inline_data():
    raw = b"RIFF_TEST_AUDIO"
    payload = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "inline_data": {
                                "mime_type": "audio/wav",
                                "data": base64.b64encode(raw).decode("ascii"),
                            }
                        }
                    ]
                }
            }
        ]
    }
    assert tts.extract_audio_bytes(payload) == raw


def test_speak_prefers_gemini_audio(monkeypatch):
    class DummyResponse:
        ok = True

        @staticmethod
        def json():
            audio = base64.b64encode(b"RIFF_FAKE").decode("ascii")
            return {
                "candidates": [
                    {"content": {"parts": [{"inline_data": {"mime_type": "audio/wav", "data": audio}}]}}
                ]
            }

    calls = {"played": 0, "gtts": 0}

    def fake_post(*args, **kwargs):
        _ = (args, kwargs)
        return DummyResponse()

    def fake_play(_path: str):
        calls["played"] += 1

    def fake_gtts(_text: str, lang: str):
        _ = lang
        calls["gtts"] += 1
        return False

    monkeypatch.setattr(tts.requests, "post", fake_post)
    monkeypatch.setattr(tts, "_play", fake_play)
    monkeypatch.setattr(tts, "_speak_with_gtts", fake_gtts)
    monkeypatch.setattr(tts.settings, "GEMINI_API_KEYS", ["test-key"])

    tts.speak("hello world", emotion="neutral", lang="en")

    assert calls["played"] == 1
    assert calls["gtts"] == 0


def test_speak_forwards_stop_event_to_player(monkeypatch):
    stop_event = object()
    seen = {"stop_event": None}

    monkeypatch.setattr(tts, "_gemini_tts_bytes", lambda *a, **k: b"RIFF_FAKE")

    def fake_play(_path: str, stop_event=None):
        seen["stop_event"] = stop_event

    monkeypatch.setattr(tts, "_play", fake_play)
    monkeypatch.setattr(tts, "_speak_with_gtts", lambda *a, **k: False)

    tts.speak("hello", stop_event=stop_event)  # type: ignore[arg-type]

    assert seen["stop_event"] is stop_event


def test_speak_falls_back_to_gtts(monkeypatch):
    calls = {"gtts": 0}

    monkeypatch.setattr(tts, "_gemini_tts_bytes", lambda *a, **k: b"")

    def fake_gtts(_text: str, lang: str, stop_event=None):
        _ = lang
        _ = stop_event
        calls["gtts"] += 1
        return True

    monkeypatch.setattr(tts, "_speak_with_gtts", fake_gtts)
    monkeypatch.setattr(tts, "_play", lambda *_: None)

    tts.speak("fallback please", emotion="neutral", lang="en")

    assert calls["gtts"] == 1


def test_speak_with_gtts_forwards_stop_event(monkeypatch):
    seen = {"stop_event": None}

    class DummyTTS:
        def __init__(self, text, lang):
            _ = (text, lang)

        def save(self, path):
            seen["path"] = path

    monkeypatch.setattr(tts, "_gemini_tts_bytes", lambda *a, **k: b"")
    import sys
    import types

    gtts_mod = types.SimpleNamespace(gTTS=DummyTTS)
    monkeypatch.setitem(sys.modules, "gtts", gtts_mod)
    monkeypatch.setattr(tts, "_play", lambda path, stop_event=None: seen.update({"stop_event": stop_event}))

    stop_event = object()
    assert tts._speak_with_gtts("hello", "en", stop_event=stop_event) is True
    assert seen["stop_event"] is stop_event
