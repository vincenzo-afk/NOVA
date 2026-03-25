"""PyQt6 GUI with streaming chat output and utility controls."""

from __future__ import annotations

import threading
from typing import Any

from vision.gemini_vision import analyze_image


def launch_gui(agent: Any) -> None:
    try:
        from PyQt6.QtCore import QTimer
        from PyQt6.QtWidgets import (
            QApplication,
            QFileDialog,
            QHBoxLayout,
            QLabel,
            QLineEdit,
            QPushButton,
            QTextEdit,
            QVBoxLayout,
            QWidget,
        )
    except Exception:  # pragma: no cover
        print("PyQt6 not installed; GUI unavailable.")
        return

    app = QApplication([])
    window = QWidget()
    window.setWindowTitle("JARVIS")

    output = QTextEdit()
    output.setReadOnly(True)
    input_box = QLineEdit()
    send_btn = QPushButton("Send")
    upload_btn = QPushButton("Upload Image")
    status_btn = QPushButton("Status")
    session_input = QLineEdit()
    session_input.setPlaceholderText("session name")
    switch_btn = QPushButton("Switch Session")
    status_label = QLabel(f"Session: {agent.session.current.name}")

    top_row = QHBoxLayout()
    top_row.addWidget(session_input)
    top_row.addWidget(switch_btn)
    top_row.addWidget(status_btn)
    top_row.addWidget(upload_btn)

    row = QHBoxLayout()
    row.addWidget(input_box)
    row.addWidget(send_btn)

    layout = QVBoxLayout()
    layout.addLayout(top_row)
    layout.addWidget(status_label)
    layout.addWidget(output)
    layout.addLayout(row)
    window.setLayout(layout)

    def send_message():
        text = input_box.text().strip()
        if not text:
            return
        input_box.clear()
        output.append(f"You: {text}")
        output.append("JARVIS: ")

        def worker():
            for token in agent.ask_stream(text):
                QTimer.singleShot(0, lambda t=token: output.insertPlainText(t))
            provider = agent.last_provider_label()
            QTimer.singleShot(0, lambda: output.append(f"\n[{provider}]\n"))

        threading.Thread(target=worker, daemon=True).start()

    def switch_session() -> None:
        name = session_input.text().strip()
        if not name:
            return
        state = agent.switch_session(name)
        status_label.setText(f"Session: {state.name}")
        output.append(f"[system] switched to session: {state.name} ({state.session_id})")

    def show_status() -> None:
        output.append(f"[status]\n{agent.status_text()}\n")

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
            output.append(f"[image] {file_path}")
            output.append(f"[image-analysis] {analysis}\n")
        except Exception as exc:
            output.append(f"[error] failed to analyze image: {exc}")

    send_btn.clicked.connect(send_message)
    input_box.returnPressed.connect(send_message)
    switch_btn.clicked.connect(switch_session)
    status_btn.clicked.connect(show_status)
    upload_btn.clicked.connect(upload_image)

    window.resize(980, 680)
    window.show()
    app.exec()
