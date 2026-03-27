from __future__ import annotations

import threading

import interfaces.voice_interface as voice_interface


def test_speak_text_forwards_stop_event(monkeypatch):
    seen = {"tts": None, "offline": None, "play": None}

    monkeypatch.setattr(voice_interface.settings, "DEFAULT_LANG", "en")
    monkeypatch.setattr(voice_interface.NetworkState, "is_online", lambda: True)
    monkeypatch.setattr(voice_interface, "speak_tamil", lambda text: "unused")
    monkeypatch.setattr(
        voice_interface,
        "tts_online",
        lambda text, emotion="neutral", lang="en", stop_event=None: seen.update({"tts": stop_event}),
    )
    monkeypatch.setattr(
        voice_interface,
        "tts_offline",
        lambda text, stop_event=None: seen.update({"offline": stop_event}),
    )

    stop_event = threading.Event()
    voice_interface._speak_text("hello", stop_event=stop_event)

    assert seen["tts"] is stop_event
    assert seen["offline"] is None


def test_speak_text_uses_offline_stop_event(monkeypatch):
    seen = {"offline": None}

    monkeypatch.setattr(voice_interface.settings, "DEFAULT_LANG", "en")
    monkeypatch.setattr(voice_interface.NetworkState, "is_online", lambda: False)
    monkeypatch.setattr(
        voice_interface,
        "tts_offline",
        lambda text, stop_event=None: seen.update({"offline": stop_event}),
    )

    stop_event = threading.Event()
    voice_interface._speak_text("hello", stop_event=stop_event)

    assert seen["offline"] is stop_event
