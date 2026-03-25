"""Voice interface loop with online/offline fallbacks."""

from __future__ import annotations

import subprocess
import threading

from config.settings import settings
from core.llm.fallback import NetworkState
from voice.stt import transcribe as stt_online
from voice.stt_offline import OfflineWhisper
from voice.tts import speak as tts_online
from voice.tts_indic import speak_tamil
from voice.tts_offline import speak as tts_offline
from voice.vad import VADRecorder
from voice.wakeword import WakeWordListener


def _transcribe_audio(audio_bytes: bytes, whisper: OfflineWhisper) -> str:
    if NetworkState.is_online():
        try:
            text = stt_online(audio_bytes, lang=settings.DEFAULT_LANG)
            if text:
                return text
        except Exception:
            pass
    return whisper.transcribe(audio_bytes, lang=settings.DEFAULT_LANG)


def _play_audio_file(path: str) -> None:
    for cmd in (["afplay", path], ["mpg123", "-q", path], ["ffplay", "-nodisp", "-autoexit", path]):
        try:
            subprocess.run(cmd, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except Exception:
            continue


def _speak_text(text: str) -> None:
    if settings.DEFAULT_LANG == "ta" and NetworkState.is_online():
        try:
            path = speak_tamil(text)
            _play_audio_file(path)
            return
        except Exception:
            pass

    if NetworkState.is_online():
        try:
            tts_online(text, lang=settings.DEFAULT_LANG)
            return
        except Exception:
            pass
    tts_offline(text)


def _wait_for_wakeword(enabled: bool, event: threading.Event) -> None:
    if not enabled:
        return
    print("Waiting for wake word...")
    event.wait()
    event.clear()


def run_voice_loop(
    agent,
    interactive_text_fallback: bool = True,
    use_wakeword: bool = False,
) -> None:
    recorder = VADRecorder(silence_ms=settings.VAD_SILENCE_MS)
    whisper = OfflineWhisper(model_size=settings.WHISPER_MODEL)
    wakeword_event = threading.Event()
    wakeword: WakeWordListener | None = None

    if use_wakeword:
        wakeword = WakeWordListener(callback=wakeword_event.set)
        wakeword.start()

    print("Voice mode started. Press Ctrl+C to stop.")
    try:
        while True:
            _wait_for_wakeword(use_wakeword, wakeword_event)

            audio = recorder.capture_until_silence()
            text = _transcribe_audio(audio, whisper) if audio else ""

            if not text and interactive_text_fallback:
                text = input("You (voice fallback) > ").strip()

            if not text:
                continue
            if text.lower() in {"/exit", "/quit", "stop voice"}:
                print("Voice mode stopped.")
                return

            print(f"You (voice) > {text}")
            response = "".join(agent.ask_stream(text))
            print(f"JARVIS > {response}")
            if wakeword:
                wakeword.set_muted(True)
            try:
                _speak_text(response)
            finally:
                if wakeword:
                    wakeword.set_muted(False)
    finally:
        if wakeword:
            wakeword.stop()
