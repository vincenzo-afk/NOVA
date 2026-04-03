"""Voice interface loop with online/offline fallbacks."""

from __future__ import annotations

import contextlib
import subprocess
import threading
import time

from config.constants import AGENT_NAME
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


def _play_audio_file(path: str, stop_event: threading.Event | None = None) -> None:
    for cmd in (["afplay", path], ["mpg123", "-q", path], ["ffplay", "-nodisp", "-autoexit", path]):
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                while proc.poll() is None:
                    if stop_event is not None and stop_event.is_set():
                        proc.terminate()
                        break
                    threading.Event().wait(0.05)
                if proc.poll() is None:
                    proc.wait(timeout=1)
            finally:
                if proc.poll() is None:
                    proc.kill()
            return
        except Exception:
            continue


def _speak_text(
    text: str,
    emotion: str = "neutral",
    stop_event: threading.Event | None = None,
) -> None:
    if settings.DEFAULT_LANG == "ta" and NetworkState.is_online():
        try:
            path = speak_tamil(text)
            _play_audio_file(path, stop_event=stop_event)
            return
        except Exception:
            pass

    if NetworkState.is_online():
        try:
            tts_online(text, emotion=emotion, lang=settings.DEFAULT_LANG, stop_event=stop_event)
            return
        except Exception:
            pass
    tts_offline(text, stop_event=stop_event)


def _wait_for_wakeword(
    enabled: bool,
    event: threading.Event,
    stop_event: threading.Event | None = None,
) -> None:
    if not enabled:
        return
    print("Waiting for wake word...")
    while True:
        if stop_event is not None and stop_event.is_set():
            return
        if event.wait(timeout=0.2):
            event.clear()
            return


def _normalize_hotkey(spec: str) -> str:
    parts = [part.strip().lower() for part in spec.split("+") if part.strip()]
    mapping = {
        "ctrl": "<ctrl>",
        "control": "<ctrl>",
        "shift": "<shift>",
        "alt": "<alt>",
        "cmd": "<cmd>",
        "command": "<cmd>",
        "win": "<cmd>",
        "meta": "<cmd>",
    }
    normalized: list[str] = []
    for part in parts:
        if part in mapping:
            normalized.append(mapping[part])
        elif part.startswith("<") and part.endswith(">"):
            # Already in angle-bracket form — keep as-is.
            normalized.append(part)
        else:
            # Bug 5 fix: pynput requires ALL key tokens to use angle brackets,
            # including single characters. Without this, the hotkey string
            # `<ctrl>+<shift>+x` is silently invalid on Linux/Mac.
            normalized.append(f"<{part}>")
    return "+".join(normalized)


def _start_barge_in_listener(on_barge_in: callable) -> object | None:
    if not settings.VOICE_BARGEIN_ENABLED:
        return None
    try:
        from pynput import keyboard
    except Exception:
        print("Barge-in hotkey unavailable; install pynput to enable Ctrl+Shift+X stop.")
        return None

    hotkey = _normalize_hotkey(settings.VOICE_BARGEIN_HOTKEY)
    hotkeys = keyboard.GlobalHotKeys({hotkey: on_barge_in})
    hotkeys.start()
    print(f"Barge-in enabled: {settings.VOICE_BARGEIN_HOTKEY} to stop speech and re-listen.")
    return hotkeys


def run_voice_loop(
    agent,
    interactive_text_fallback: bool = True,
    use_wakeword: bool = False,
    stop_event: threading.Event | None = None,
) -> None:
    recorder = VADRecorder(silence_ms=settings.VAD_SILENCE_MS)
    whisper = OfflineWhisper(model_size=settings.WHISPER_MODEL)
    wakeword_event = threading.Event()
    wakeword: WakeWordListener | None = None
    barge_in_event = threading.Event()
    hotkey_listener = _start_barge_in_listener(barge_in_event.set)

    if use_wakeword:
        wakeword = WakeWordListener(callback=wakeword_event.set)
        wakeword.start()

    print("Voice mode started. Press Ctrl+C to stop.")
    capture_thread: threading.Thread | None = None
    try:
        while True:
            if capture_thread is not None and capture_thread.is_alive():
                capture_thread.join(timeout=0.5)
                if capture_thread.is_alive():
                    print("[voice] previous capture still busy; waiting before retry.")
                    time.sleep(0.2)
                    continue
            if stop_event is not None and stop_event.is_set():
                print("Voice mode stopped.")
                return
            barge_in_event.clear()
            _wait_for_wakeword(use_wakeword, wakeword_event, stop_event=stop_event)
            if stop_event is not None and stop_event.is_set():
                print("Voice mode stopped.")
                return

            audio: bytes = b""
            capture_done = threading.Event()
            capture_result: dict[str, bytes] = {"audio": b""}

            def _capture_job() -> None:
                try:
                    capture_result["audio"] = recorder.capture_until_silence() or b""
                except Exception:
                    capture_result["audio"] = b""
                finally:
                    capture_done.set()

            capture_thread = threading.Thread(target=_capture_job, daemon=True)
            capture_thread.start()
            max_capture_seconds = max(5.0, float(getattr(settings, "VOICE_MAX_CAPTURE_SECONDS", 30.0)))
            capture_done.wait(timeout=max_capture_seconds)
            if not capture_done.is_set():
                print(f"[voice] capture timeout after {max_capture_seconds:.0f}s; retrying.")
                capture_thread.join(timeout=0.5)
                continue
            audio = capture_result.get("audio", b"")
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
            print(f"{AGENT_NAME} > {response}")
            if wakeword:
                wakeword.set_muted(True)
            try:
                emotion = getattr(agent, "emotion_state", "neutral")
                _speak_text(response, emotion=emotion, stop_event=barge_in_event)
                if barge_in_event.is_set():
                    print("[voice] Barge-in received; listening again.")
                    continue
            finally:
                if wakeword:
                    wakeword.set_muted(False)
    finally:
        with contextlib.suppress(Exception):
            if capture_thread is not None and capture_thread.is_alive():
                capture_thread.join(timeout=1.0)
        with contextlib.suppress(Exception):
            if hotkey_listener is not None:
                hotkey_listener.stop()
        if wakeword:
            wakeword.stop()
