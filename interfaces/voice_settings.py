"""Voice engine settings dialog (STT/TTS per language)."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _update_env(updates: dict[str, str]) -> None:
    env_path = Path(".env")
    if not env_path.exists():
        return
    lines = env_path.read_text(encoding="utf-8").splitlines()
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            out.append(line)
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in updates:
            out.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            out.append(line)
    for key, value in updates.items():
        if key not in seen:
            out.append(f"{key}={value}")
    env_path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")


def open_voice_settings_dialog(settings_obj: Any, parent: Any = None) -> None:
    try:
        from PyQt6.QtWidgets import (
            QComboBox,
            QDialog,
            QFormLayout,
            QMessageBox,
            QPushButton,
            QVBoxLayout,
        )
    except Exception:
        return

    dlg = QDialog(parent)
    dlg.setWindowTitle("Voice Settings")
    root = QVBoxLayout()
    form = QFormLayout()

    lang_combo = QComboBox()
    lang_combo.addItems(["en", "ta", "hi"])
    lang_combo.setCurrentText(str(getattr(settings_obj, "DEFAULT_LANG", "en")))

    stt_combo = QComboBox()
    stt_combo.addItems(["gemini_online", "faster_whisper"])
    stt_combo.setCurrentText("gemini_online")

    whisper_combo = QComboBox()
    whisper_combo.addItems(["base", "small", "medium", "large"])
    whisper_combo.setCurrentText(str(getattr(settings_obj, "WHISPER_MODEL", "base")))

    tts_combo = QComboBox()
    tts_combo.addItems(["gemini_online", "gtts", "pyttsx3_offline", "indictts_tamil"])

    voice_combo = QComboBox()
    voice_combo.addItems(["Kore", "Aoede", "Fenrir", "Leda"])
    voice_combo.setCurrentText(str(getattr(settings_obj, "GEMINI_TTS_VOICE", "Kore")))

    form.addRow("Language", lang_combo)
    form.addRow("STT Engine", stt_combo)
    form.addRow("Whisper Model", whisper_combo)
    form.addRow("TTS Engine", tts_combo)
    form.addRow("Gemini Voice", voice_combo)
    root.addLayout(form)

    save_btn = QPushButton("Save")
    root.addWidget(save_btn)
    dlg.setLayout(root)

    def save() -> None:
        updates = {
            "DEFAULT_LANG": lang_combo.currentText().strip(),
            "WHISPER_MODEL": whisper_combo.currentText().strip(),
            "GEMINI_TTS_VOICE": voice_combo.currentText().strip(),
        }
        _update_env(updates)
        for key, value in updates.items():
            try:
                setattr(settings_obj, key, value)
            except Exception:
                pass
        QMessageBox.information(dlg, "Voice Settings", "Saved. Restart voice loop for full effect.")
        dlg.close()

    save_btn.clicked.connect(save)
    dlg.resize(420, 260)
    dlg.exec()
