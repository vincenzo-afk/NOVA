"""PyQt6 GUI with streaming chat, status widgets, and utility controls."""

from __future__ import annotations

import threading
import hashlib
import hmac
import time
from typing import Any

from config.constants import CLI_PIN_HASH_FILE, CLI_PIN_LEGACY_FILE, CLI_PIN_LOCK_FILE
from config.settings import settings
from core.llm.fallback import NetworkState
from vision.gemini_vision import analyze_image
from utils.events import format_event_log
from utils.goals import format_goal_list
from utils.health import format_health_table, summarize_health


def build_status_snapshot(agent: Any) -> dict[str, Any]:
    session_name = getattr(getattr(agent, "session", None), "current", None)
    session_name = getattr(session_name, "name", "unknown")
    session_id = getattr(getattr(agent, "session", None), "current", None)
    session_id = getattr(session_id, "session_id", "")

    tokens_today = 0
    try:
        tokens_today = int(agent.usage.total_tokens_today(session_id=session_id))
    except Exception:
        tokens_today = 0

    try:
        active_keys = int(agent.engine.pool.active_count())
    except Exception:
        active_keys = 0

    return {
        "session": session_name,
        "provider": str(getattr(agent, "last_provider_label", lambda: "unknown")()),
        "emotion": str(getattr(agent, "emotion_state", "neutral")),
        "muted": bool(getattr(agent, "is_muted", lambda: False)()),
        "online": bool(NetworkState.is_online()),
        "tokens_today": tokens_today,
        "active_keys": active_keys,
    }


def format_status_line(snapshot: dict[str, Any]) -> str:
    mode = "Online" if snapshot.get("online") else "Offline"
    mute = "Muted" if snapshot.get("muted") else "Live"
    session = snapshot.get("session", "unknown")
    provider = snapshot.get("provider", "unknown")
    emotion = snapshot.get("emotion", "neutral")
    return (
        f"Session: {session} | Mode: {mode} | Emotion: {emotion} | "
        f"Provider: {provider} | Alerts: {mute}"
    )


def format_usage_line(snapshot: dict[str, Any]) -> str:
    tokens = int(snapshot.get("tokens_today", 0))
    active_keys = int(snapshot.get("active_keys", 0))
    return f"Today: {tokens} tokens | Active cloud keys: {active_keys}"


def launch_gui(agent: Any) -> None:
    try:
        from PyQt6.QtCore import QTimer
        from PyQt6.QtWidgets import (
            QApplication,
            QFileDialog,
            QHBoxLayout,
            QLabel,
            QLineEdit,
            QInputDialog,
            QPushButton,
            QTextEdit,
            QVBoxLayout,
            QWidget,
        )
    except Exception:  # pragma: no cover
        print("PyQt6 not installed; GUI unavailable.")
        return

    app = QApplication([])

    def _verify_pin(entered: str, stored: str) -> bool:
        value = (stored or "").strip()
        if not value:
            return True
        if value.startswith("pbkdf2_sha256$"):
            try:
                _algo, iterations, salt, expected = value.split("$", 3)
                digest = hashlib.pbkdf2_hmac(
                    "sha256",
                    entered.encode("utf-8"),
                    salt.encode("utf-8"),
                    int(iterations),
                ).hex()
                return hmac.compare_digest(digest, expected)
            except Exception:
                return False
        return hmac.compare_digest(entered, value)

    # Reuse CLI PIN policy in GUI (hash file first, then legacy plaintext file).
    from pathlib import Path

    pin_hash = ""
    pin_hash_file = Path(CLI_PIN_HASH_FILE)
    legacy_pin_file = Path(CLI_PIN_LEGACY_FILE)
    lock_file = _resolve_lock_file(CLI_PIN_LOCK_FILE)
    if pin_hash_file.exists():
        pin_hash = pin_hash_file.read_text(encoding="utf-8").strip()
    elif legacy_pin_file.exists():
        pin_hash = legacy_pin_file.read_text(encoding="utf-8").strip()

    if pin_hash:
        if lock_file.exists():
            try:
                unlock_at = float(lock_file.read_text(encoding="utf-8").strip() or "0")
                if time.time() < unlock_at:
                    return
            except Exception:
                pass
        failed = 0
        while failed < 5:
            entered, ok = QInputDialog.getText(
                None,
                "NOVA Authentication",
                "Enter CLI PIN:",
                echo=QLineEdit.EchoMode.Password,
            )
            if not ok:
                return
            if _verify_pin(str(entered), pin_hash):
                try:
                    lock_file.unlink(missing_ok=True)
                except Exception:
                    pass
                break
            failed += 1
            try:
                lock_file.parent.mkdir(parents=True, exist_ok=True)
                lock_until = time.time() + min(300, 2 ** failed)
                lock_file.write_text(str(lock_until), encoding="utf-8")
                try:
                    lock_file.chmod(0o600)
                except Exception:
                    pass
            except Exception:
                pass
            time.sleep(min(30, 2 ** failed))
        else:
            lock_file.parent.mkdir(parents=True, exist_ok=True)
            lock_file.write_text(str(time.time() + 300), encoding="utf-8")
            try:
                lock_file.chmod(0o600)
            except Exception:
                pass
            return

    window = QWidget()
    window.setWindowTitle("NOVA")

    output = QTextEdit()
    output.setReadOnly(True)
    input_box = QLineEdit()
    input_box.setPlaceholderText("Type a message...")

    send_btn = QPushButton("Send")
    mic_btn = QPushButton("Mic (One Shot)")
    upload_btn = QPushButton("Upload Image")
    export_btn = QPushButton("Export")
    mute_btn = QPushButton("Mute")
    status_btn = QPushButton("Status JSON")
    goal_input = QLineEdit()
    goal_input.setPlaceholderText("goal description")
    goal_id_input = QLineEdit()
    goal_id_input.setPlaceholderText("goal id")
    goal_add_btn = QPushButton("Add Goal")
    goal_refresh_btn = QPushButton("Refresh Goals")
    goal_resume_btn = QPushButton("Resume Goal")
    goal_cancel_btn = QPushButton("Cancel Goal")
    goal_output = QTextEdit()
    goal_output.setReadOnly(True)
    goal_output.setMinimumHeight(120)
    event_output = QTextEdit()
    event_output.setReadOnly(True)
    event_output.setMinimumHeight(120)
    alert_refresh_btn = QPushButton("Refresh Alerts")
    health_refresh_btn = QPushButton("Refresh Health")
    health_output = QTextEdit()
    health_output.setReadOnly(True)
    health_output.setMinimumHeight(120)

    session_input = QLineEdit()
    session_input.setPlaceholderText("session name")
    switch_btn = QPushButton("Switch Session")

    status_label = QLabel("Status: loading...")
    usage_label = QLabel("Today: 0 tokens")

    whisper_holder: dict[str, Any] = {"instance": None}
    mic_lock = threading.Lock()

    def refresh_status() -> None:
        snapshot = build_status_snapshot(agent)
        status_label.setText(format_status_line(snapshot))
        usage_label.setText(format_usage_line(snapshot))
        mute_btn.setText("Unmute" if snapshot.get("muted") else "Mute")

    def append_line(text: str) -> None:
        output.append(text)

    def stream_prompt(prompt: str, heading: str = "NOVA") -> None:
        append_line(f"{heading}: ")

        def worker() -> None:
            for token in agent.ask_stream(prompt):
                QTimer.singleShot(0, lambda t=token: output.insertPlainText(t))
            provider = agent.last_provider_label()
            QTimer.singleShot(0, lambda: output.append(f"\n[{provider}]\n"))
            QTimer.singleShot(0, refresh_status)

        threading.Thread(target=worker, daemon=True).start()

    def send_message() -> None:
        text = input_box.text().strip()
        if not text:
            return
        if len(text) > 50_000:
            append_line("[system] Input too long. Please keep messages under 50,000 characters.")
            return
        input_box.clear()
        append_line(f"You: {text}")
        stream_prompt(text)

    def switch_session() -> None:
        name = session_input.text().strip()
        if not name:
            return
        state = agent.switch_session(name)
        append_line(f"[system] switched to session: {state.name} ({state.session_id})")
        refresh_status()

    def show_status_json() -> None:
        append_line(f"[status]\n{agent.status_text()}\n")
        refresh_status()

    def refresh_goals() -> None:
        try:
            goal_output.setPlainText(format_goal_list(agent.list_goals()))
        except Exception as exc:
            goal_output.setPlainText(f"Failed to load goals: {exc}")

    def refresh_health() -> None:
        try:
            items = agent.health.status_table()
            summary = summarize_health(items)
            health_output.setPlainText(f"Summary: {summary}\n\n{format_health_table(items)}")
        except Exception as exc:
            health_output.setPlainText(f"Failed to load health: {exc}")

    def refresh_events() -> None:
        try:
            events = agent.recent_events()
            event_output.setPlainText(format_event_log(events))
        except Exception as exc:
            event_output.setPlainText(f"Failed to load alerts: {exc}")

    def export_session() -> None:
        try:
            path = agent.export_session("md")
            append_line(f"[export] session exported -> {path}")
        except Exception as exc:
            append_line(f"[error] export failed: {exc}")

    def toggle_mute() -> None:
        muted = agent.toggle_mute()
        append_line("[system] muted proactive alerts" if muted else "[system] unmuted proactive alerts")
        refresh_status()

    def add_goal() -> None:
        goal = goal_input.text().strip()
        if not goal:
            append_line("[goal] enter a goal description first")
            return
        try:
            result = agent.add_goal(goal)
            append_line(f"[goal] {result}")
            goal_input.clear()
            refresh_goals()
        except Exception as exc:
            append_line(f"[goal-error] {exc}")

    def resume_goal() -> None:
        goal_id = goal_id_input.text().strip()
        if not goal_id:
            append_line("[goal] enter a goal id first")
            return
        try:
            result = agent.resume_goal(goal_id)
            append_line(f"[goal] {result}")
            refresh_goals()
        except Exception as exc:
            append_line(f"[goal-error] {exc}")

    def cancel_goal() -> None:
        goal_id = goal_id_input.text().strip()
        if not goal_id:
            append_line("[goal] enter a goal id first")
            return
        try:
            result = agent.cancel_goal(goal_id)
            append_line(f"[goal] {result}")
            refresh_goals()
        except Exception as exc:
            append_line(f"[goal-error] {exc}")

    def upload_image() -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            window,
            "Select Image",
            "",
            "Images (*.png *.jpg *.jpeg *.webp *.bmp)",
        )
        if not file_path:
            return
        try:
            with open(file_path, "rb") as image_file:
                image_bytes = image_file.read()
            analysis = analyze_image(image_bytes)
            append_line(f"[image] {file_path}")
            append_line(f"[image-analysis] {analysis}")
            prompt = (
                "User uploaded an image in GUI. "
                "Use this analysis and assist with next steps.\n"
                f"Image analysis JSON: {analysis}"
            )
            stream_prompt(prompt, heading="NOVA (image)")
        except Exception as exc:
            append_line(f"[error] failed to analyze image: {exc}")

    def mic_one_shot() -> None:
        if not mic_lock.acquire(blocking=False):
            append_line("[voice] microphone capture already running")
            return
        append_line("[voice] listening...")

        def worker() -> None:
            try:
                from voice.stt import transcribe as stt_online
                from voice.stt_offline import OfflineWhisper
                from voice.vad import VADRecorder

                recorder = VADRecorder(silence_ms=settings.VAD_SILENCE_MS)
                audio = recorder.capture_until_silence()
                if not audio:
                    QTimer.singleShot(0, lambda: append_line("[voice] no speech detected"))
                    return

                text = ""
                if NetworkState.is_online():
                    try:
                        text = stt_online(audio, lang=settings.DEFAULT_LANG)
                    except Exception:
                        text = ""

                if not text:
                    if whisper_holder["instance"] is None:
                        whisper_holder["instance"] = OfflineWhisper(model_size=settings.WHISPER_MODEL)
                    text = whisper_holder["instance"].transcribe(audio, lang=settings.DEFAULT_LANG)

                text = text.strip()
                if not text:
                    QTimer.singleShot(0, lambda: append_line("[voice] transcription empty"))
                    return

                def _submit_transcript() -> None:
                    append_line(f"You (voice): {text}")
                    stream_prompt(text)

                QTimer.singleShot(0, _submit_transcript)
            except Exception as exc:
                QTimer.singleShot(0, lambda: append_line(f"[voice-error] {exc}"))
            finally:
                mic_lock.release()

        threading.Thread(target=worker, daemon=True).start()

    # Top controls
    top_row = QHBoxLayout()
    top_row.addWidget(session_input)
    top_row.addWidget(switch_btn)
    top_row.addWidget(status_btn)
    top_row.addWidget(upload_btn)
    top_row.addWidget(mic_btn)
    top_row.addWidget(export_btn)
    top_row.addWidget(mute_btn)

    goal_controls = QHBoxLayout()
    goal_controls.addWidget(goal_input)
    goal_controls.addWidget(goal_add_btn)
    goal_controls.addWidget(goal_id_input)
    goal_controls.addWidget(goal_resume_btn)
    goal_controls.addWidget(goal_cancel_btn)
    goal_controls.addWidget(goal_refresh_btn)
    goal_controls.addWidget(alert_refresh_btn)
    goal_controls.addWidget(health_refresh_btn)

    # Chat input row
    input_row = QHBoxLayout()
    input_row.addWidget(input_box)
    input_row.addWidget(send_btn)

    layout = QVBoxLayout()
    layout.addLayout(top_row)
    layout.addWidget(status_label)
    layout.addWidget(usage_label)
    layout.addWidget(goal_output)
    layout.addWidget(event_output)
    layout.addWidget(health_output)
    layout.addLayout(goal_controls)
    layout.addWidget(output)
    layout.addLayout(input_row)
    window.setLayout(layout)

    send_btn.clicked.connect(send_message)
    input_box.returnPressed.connect(send_message)
    switch_btn.clicked.connect(switch_session)
    status_btn.clicked.connect(show_status_json)
    upload_btn.clicked.connect(upload_image)
    mic_btn.clicked.connect(mic_one_shot)
    export_btn.clicked.connect(export_session)
    mute_btn.clicked.connect(toggle_mute)
    goal_add_btn.clicked.connect(add_goal)
    goal_resume_btn.clicked.connect(resume_goal)
    goal_cancel_btn.clicked.connect(cancel_goal)
    goal_refresh_btn.clicked.connect(refresh_goals)
    alert_refresh_btn.clicked.connect(refresh_events)
    health_refresh_btn.clicked.connect(refresh_health)

    # Periodic status refresh
    timer = QTimer()
    timer.timeout.connect(refresh_status)
    timer.timeout.connect(refresh_events)
    timer.start(3000)
    refresh_status()
    refresh_goals()
    refresh_events()
    refresh_health()

    window.resize(1080, 760)
    window.show()
    app.exec()
    def _resolve_lock_file(path_value: str):
        p = Path(path_value).expanduser()
        if p.is_absolute():
            return p
        return Path.home() / path_value.lstrip("./")
