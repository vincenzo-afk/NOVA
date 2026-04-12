"""NOVA PyQt6 GUI — Deep-space dark redesign with neon-cyan accents.

Layout: left sidebar (7 sections) + main content area.
Sections: Chat · Voice · Autonomy · Integrations · Settings · Profiles · Debug

Features wired:
  - Streaming chat with provider badge
  - Voice one-shot + continuous loop + animated mic button
  - Goal add/cancel/resume with live list
  - Mission management panel
  - Emergency STOP button (always visible)
  - Daily token progress bar
  - Ollama + OmniParser live health dots (Debug tab)
  - Live settings mutation via nova_settings_manager
  - Profile save/load selector
  - Key Manager, Model Manager dialogs preserved
"""

from __future__ import annotations

import hashlib
import hmac
import json
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from config.constants import CLI_PIN_HASH_FILE, CLI_PIN_LEGACY_FILE, CLI_PIN_LOCK_FILE
from config.settings import settings
from core.llm.fallback import NetworkState
from vision.gemini_vision import analyze_image
from utils.events import format_event_log
from utils.goals import format_goal_list
from utils.health import format_health_table, summarize_health


# ── Colour palette ──────────────────────────────────────────────────────────
_BG        = "#0a0e17"
_BG2       = "#111827"
_BG3       = "#1a2235"
_PANEL     = "#141c2e"
_PANEL2    = "#1e2d42"
_SIDEBAR   = "#0d1527"
_ACCENT    = "#00e5ff"
_ACCENT2   = "#0097a7"
_ACCENT3   = "#00b8d4"
_TEXT      = "#e2e8f0"
_TEXT2     = "#94a3b8"
_TEXT3     = "#64748b"
_SUCCESS   = "#22c55e"
_WARNING   = "#f59e0b"
_ERROR     = "#ef4444"
_BORDER    = "#1e3a5f"
_HOVER     = "#1e3a5f"
_SELECTED  = "#0e2a45"


# ── Global stylesheet ───────────────────────────────────────────────────────
_GLOBAL_STYLE = f"""
QWidget {{
    background-color: {_BG};
    color: {_TEXT};
    font-family: 'Inter', 'Segoe UI', 'SF Pro Display', sans-serif;
    font-size: 13px;
}}
QScrollBar:vertical {{
    background: {_BG2};
    width: 8px;
    border-radius: 4px;
}}
QScrollBar::handle:vertical {{
    background: {_BORDER};
    border-radius: 4px;
    min-height: 20px;
}}
QScrollBar::handle:vertical:hover {{
    background: {_ACCENT2};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar:horizontal {{
    background: {_BG2};
    height: 8px;
    border-radius: 4px;
}}
QScrollBar::handle:horizontal {{
    background: {_BORDER};
    border-radius: 4px;
}}
QToolTip {{
    background-color: {_PANEL2};
    color: {_TEXT};
    border: 1px solid {_BORDER};
    padding: 4px 8px;
    border-radius: 4px;
}}
"""

_SIDEBAR_BTN_STYLE = f"""
QPushButton {{
    background: transparent;
    color: {_TEXT2};
    border: none;
    text-align: left;
    padding: 10px 16px;
    border-radius: 8px;
    font-size: 13px;
    font-weight: 500;
}}
QPushButton:hover {{
    background: {_HOVER};
    color: {_TEXT};
}}
QPushButton[active="true"] {{
    background: {_SELECTED};
    color: {_ACCENT};
    border-left: 3px solid {_ACCENT};
    padding-left: 13px;
}}
"""

_PRIMARY_BTN = f"""
QPushButton {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
        stop:0 {_ACCENT2}, stop:1 {_ACCENT3});
    color: #000;
    border: none;
    padding: 8px 18px;
    border-radius: 8px;
    font-weight: 600;
    font-size: 13px;
}}
QPushButton:hover {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
        stop:0 {_ACCENT3}, stop:1 {_ACCENT});
}}
QPushButton:pressed {{ opacity: 0.8; }}
QPushButton:disabled {{ background: {_PANEL2}; color: {_TEXT3}; }}
"""

_DANGER_BTN = f"""
QPushButton {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
        stop:0 #7f0000, stop:1 {_ERROR});
    color: white;
    border: none;
    padding: 8px 18px;
    border-radius: 8px;
    font-weight: 700;
    font-size: 13px;
}}
QPushButton:hover {{
    background: {_ERROR};
}}
"""

_GHOST_BTN = f"""
QPushButton {{
    background: transparent;
    color: {_ACCENT};
    border: 1px solid {_ACCENT2};
    padding: 7px 14px;
    border-radius: 8px;
    font-size: 12px;
}}
QPushButton:hover {{
    background: {_SELECTED};
    border-color: {_ACCENT};
}}
QPushButton:disabled {{ color: {_TEXT3}; border-color: {_PANEL2}; }}
"""

_INPUT_STYLE = f"""
QLineEdit, QTextEdit, QPlainTextEdit {{
    background: {_PANEL};
    color: {_TEXT};
    border: 1px solid {_BORDER};
    border-radius: 8px;
    padding: 8px 12px;
    selection-background-color: {_ACCENT2};
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{
    border: 1px solid {_ACCENT};
    outline: none;
}}
QLineEdit::placeholder, QPlainTextEdit::placeholder {{
    color: {_TEXT3};
}}
"""

_CHAT_STYLE = f"""
QTextEdit {{
    background: {_BG2};
    color: {_TEXT};
    border: none;
    border-radius: 0;
    padding: 16px;
    font-size: 14px;
    line-height: 1.6;
    selection-background-color: {_ACCENT2};
}}
"""

_COMBO_STYLE = f"""
QComboBox {{
    background: {_PANEL};
    color: {_TEXT};
    border: 1px solid {_BORDER};
    border-radius: 8px;
    padding: 7px 12px;
}}
QComboBox:hover {{ border-color: {_ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox QAbstractItemView {{
    background: {_PANEL2};
    color: {_TEXT};
    border: 1px solid {_BORDER};
    selection-background-color: {_SELECTED};
}}
"""

_LABEL_STYLE = f"QLabel {{ color: {_TEXT}; background: transparent; }}"
_MUTED_LABEL = f"QLabel {{ color: {_TEXT2}; background: transparent; font-size: 12px; }}"
_HEADER_LABEL = f"QLabel {{ color: {_ACCENT}; background: transparent; font-size: 16px; font-weight: 700; letter-spacing: 1px; }}"

_CHECKBOX_STYLE = f"""
QCheckBox {{
    color: {_TEXT};
    spacing: 8px;
}}
QCheckBox::indicator {{
    width: 16px; height: 16px;
    border: 1px solid {_BORDER};
    border-radius: 4px;
    background: {_PANEL};
}}
QCheckBox::indicator:checked {{
    background: {_ACCENT2};
    border-color: {_ACCENT};
}}
"""

_PROGRESS_STYLE = f"""
QProgressBar {{
    background: {_PANEL};
    border: 1px solid {_BORDER};
    border-radius: 6px;
    height: 10px;
    text-align: center;
    font-size: 10px;
    color: {_TEXT};
}}
QProgressBar::chunk {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
        stop:0 {_ACCENT2}, stop:1 {_ACCENT});
    border-radius: 6px;
}}
"""

_SEPARATOR_STYLE = f"QFrame {{ background: {_BORDER}; max-height: 1px; }}"

_STATUS_BAR_STYLE = f"""
QWidget#statusBar {{
    background: {_SIDEBAR};
    border-top: 1px solid {_BORDER};
}}
"""


def _resolve_lock_file(path_value: str) -> Path:
    p = Path(path_value).expanduser()
    if p.is_absolute():
        return p
    return Path.home() / path_value.lstrip("./")


def build_status_snapshot(agent: Any) -> dict[str, Any]:
    session_name = getattr(getattr(agent, "session", None), "current", None)
    session_name = getattr(session_name, "name", "unknown")
    session_id = getattr(getattr(agent, "session", None), "current", None)
    session_id = getattr(session_id, "session_id", "")
    tokens_today = 0
    try:
        tokens_today = int(agent.usage.total_tokens_today(session_id=session_id))
    except Exception:
        pass
    try:
        pool = getattr(getattr(agent, "engine", None), "pool", None)
        active_keys = int(pool.active_count()) if pool is not None else 0
    except Exception:
        active_keys = 0
    return {
        "session": session_name,
        "provider": str(getattr(agent, "last_provider_label", lambda: "unknown")()),
        "emotion": str(getattr(agent, "emotion_state", "neutral")),
        "privacy_mode": str(getattr(agent, "_get_session_privacy_mode", lambda *_: "full_cloud")()),
        "muted": bool(getattr(agent, "is_muted", lambda: False)()),
        "online": bool(NetworkState.is_online()),
        "tokens_today": tokens_today,
        "active_keys": active_keys,
    }


# ── Status dot widget ────────────────────────────────────────────────────────

def _make_status_dot(color: str = _SUCCESS) -> "QLabel":
    from PyQt6.QtWidgets import QLabel
    from PyQt6.QtCore import Qt
    dot = QLabel("●")
    dot.setStyleSheet(f"QLabel {{ color: {color}; font-size: 10px; background: transparent; }}")
    dot.setToolTip("Service status")
    return dot


# ── Animated mic button ──────────────────────────────────────────────────────

def _build_mic_btn():
    from PyQt6.QtWidgets import QPushButton
    from PyQt6.QtCore import QTimer, QPropertyAnimation, QRect
    btn = QPushButton("🎤  Mic")
    btn.setStyleSheet(_PRIMARY_BTN)
    btn.setFixedHeight(36)
    btn._anim_active = False
    btn._anim_tick = 0

    def _start_anim():
        btn._anim_active = True
        _tick()

    def _stop_anim():
        btn._anim_active = False
        btn.setText("🎤  Mic")
        btn.setStyleSheet(_PRIMARY_BTN)

    def _tick():
        if not btn._anim_active:
            return
        btn._anim_tick += 1
        wave = ["▁", "▂", "▃", "▄", "▅", "▆", "▇", "██","▇","▆","▅","▄","▃","▂"]
        w = wave[btn._anim_tick % len(wave)]
        btn.setText(f"🎤 {w}")
        btn.setStyleSheet(_PRIMARY_BTN + f"\nQPushButton {{ border: 1px solid {_ACCENT}; }}")
        QTimer.singleShot(100, _tick)

    btn._start_anim = _start_anim
    btn._stop_anim = _stop_anim
    return btn


# ── Card widget ──────────────────────────────────────────────────────────────

def _make_card(parent=None):
    from PyQt6.QtWidgets import QFrame, QVBoxLayout
    card = QFrame(parent)
    card.setStyleSheet(f"""
        QFrame {{
            background: {_PANEL};
            border: 1px solid {_BORDER};
            border-radius: 12px;
        }}
    """)
    layout = QVBoxLayout(card)
    layout.setContentsMargins(16, 14, 16, 14)
    layout.setSpacing(8)
    return card, layout


def _section_label(text: str, parent=None):
    from PyQt6.QtWidgets import QLabel
    lbl = QLabel(text, parent)
    lbl.setStyleSheet(f"QLabel {{ color: {_TEXT3}; font-size: 10px; font-weight: 600; letter-spacing: 2px; background: transparent; }}")
    return lbl


def _h_sep(parent=None):
    from PyQt6.QtWidgets import QFrame
    sep = QFrame(parent)
    sep.setFrameShape(QFrame.Shape.HLine)
    sep.setStyleSheet(_SEPARATOR_STYLE)
    return sep


# ── Main launch function ─────────────────────────────────────────────────────

def launch_gui(agent: Any, notify_fn: Any | None = None) -> None:
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError("launch_gui must be called from the main thread")
    try:
        from PyQt6.QtCore import Qt, QTimer, QSize
        from PyQt6.QtGui import QFont, QIcon, QColor, QPalette
        from PyQt6.QtWidgets import (
            QApplication, QCheckBox, QComboBox, QDialog,
            QFileDialog, QFrame, QGridLayout, QHBoxLayout,
            QInputDialog, QLabel, QLineEdit, QMessageBox,
            QPlainTextEdit, QProgressBar, QPushButton,
            QScrollArea, QSizePolicy, QSplitter,
            QStackedWidget, QTextEdit, QVBoxLayout, QWidget,
        )
    except Exception:
        print("PyQt6 not installed; GUI unavailable.")
        if callable(notify_fn):
            try:
                notify_fn("NOVA GUI", "PyQt6 not installed; GUI unavailable.")
            except Exception:
                pass
        return

    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(_GLOBAL_STYLE + _INPUT_STYLE + _COMBO_STYLE + _LABEL_STYLE + _CHECKBOX_STYLE + _PROGRESS_STYLE)

    # ── PIN auth (reuse existing logic) ───────────────────────────────────────
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

    pin_hash = ""
    pin_hash_file = Path(CLI_PIN_HASH_FILE)
    legacy_pin_file = Path(CLI_PIN_LEGACY_FILE)
    lock_file = _resolve_lock_file(CLI_PIN_LOCK_FILE)
    if pin_hash_file.exists():
        try:
            pin_hash = pin_hash_file.read_text(encoding="utf-8").strip()
        except Exception:
            pass
    elif legacy_pin_file.exists():
        try:
            pin_hash = legacy_pin_file.read_text(encoding="utf-8").strip()
        except Exception:
            pass

    if pin_hash:
        if lock_file.exists():
            try:
                unlock_at = float(lock_file.read_text(encoding="utf-8").strip() or "0")
                if time.time() < unlock_at:
                    QMessageBox.critical(None, "NOVA Locked",
                                         "Too many failed attempts. Try again later.")
                    return
            except Exception:
                pass
        failed = 0
        while failed < 5:
            entered, ok = QInputDialog.getText(
                None, "NOVA Authentication", "Enter CLI PIN:",
                echo=QLineEdit.EchoMode.Password,
            )
            if not ok:
                return
            if _verify_pin(str(entered), pin_hash):
                lock_file.unlink(missing_ok=True)
                break
            failed += 1
            lock_until = time.time() + min(300, 2 ** failed)
            try:
                lock_file.parent.mkdir(parents=True, exist_ok=True)
                lock_file.write_text(str(lock_until), encoding="utf-8")
                lock_file.chmod(0o600)
            except Exception:
                pass
            time.sleep(min(30, 2 ** failed))
        else:
            lock_file.parent.mkdir(parents=True, exist_ok=True)
            lock_file.write_text(str(time.time() + 300), encoding="utf-8")
            return

    # ── State ──────────────────────────────────────────────────────────────
    whisper_holder: dict[str, Any] = {"instance": None}
    mic_lock = threading.Lock()
    voice_loop_state: dict[str, Any] = {"thread": None, "stop_event": None}
    theme_state: dict[str, str] = {"current": ""}
    _svc_health: dict[str, Any] = {}

    # ── Root layout: sidebar + main stack ─────────────────────────────────
    root = QWidget()
    root.setWindowTitle("NOVA")
    root.setObjectName("nova_root")
    root_layout = QHBoxLayout(root)
    root_layout.setContentsMargins(0, 0, 0, 0)
    root_layout.setSpacing(0)

    # ── Sidebar ───────────────────────────────────────────────────────────
    sidebar = QWidget()
    sidebar.setFixedWidth(210)
    sidebar.setStyleSheet(f"QWidget {{ background: {_SIDEBAR}; border-right: 1px solid {_BORDER}; }}")
    sidebar_layout = QVBoxLayout(sidebar)
    sidebar_layout.setContentsMargins(12, 20, 12, 20)
    sidebar_layout.setSpacing(4)

    logo_label = QLabel("◈ NOVA")
    logo_label.setStyleSheet(f"QLabel {{ color: {_ACCENT}; font-size: 22px; font-weight: 800; letter-spacing: 3px; background: transparent; padding-bottom: 8px; }}")
    sidebar_layout.addWidget(logo_label)
    sidebar_layout.addWidget(_h_sep())
    sidebar_layout.addSpacing(8)

    PAGES = [
        ("💬", "Chat"),
        ("🎤", "Voice"),
        ("🤖", "Autonomy"),
        ("🔗", "Integrations"),
        ("⚙️", "Settings"),
        ("📋", "Profiles"),
        ("🛠️", "Debug"),
    ]

    nav_buttons: list[QPushButton] = []
    stacked = QStackedWidget()

    def _switch_page(idx: int) -> None:
        stacked.setCurrentIndex(idx)
        for i, btn in enumerate(nav_buttons):
            btn.setProperty("active", str(i == idx).lower())
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    for icon_char, name in PAGES:
        btn = QPushButton(f"  {icon_char}  {name}")
        btn.setStyleSheet(_SIDEBAR_BTN_STYLE)
        btn.setFixedHeight(40)
        page_idx = len(nav_buttons)
        btn.clicked.connect(lambda checked=False, i=page_idx: _switch_page(i))
        sidebar_layout.addWidget(btn)
        nav_buttons.append(btn)

    sidebar_layout.addStretch()
    sidebar_layout.addWidget(_h_sep())

    # Emergency STOP button — always visible in sidebar
    stop_btn = QPushButton("⚡ EMERGENCY STOP")
    stop_btn.setStyleSheet(_DANGER_BTN)
    stop_btn.setFixedHeight(42)
    stop_btn.setToolTip("Immediately halt all autonomy tasks")
    sidebar_layout.addSpacing(8)
    sidebar_layout.addWidget(stop_btn)

    def _emergency_stop() -> None:
        try:
            from safety.guardrails import guardrails
            guardrails.emergency_stop()
            stop_btn.setText("🛑 STOPPED")
            stop_btn.setStyleSheet(f"QPushButton {{ background: {_ERROR}; color: white; border: none; padding: 10px; border-radius: 8px; font-weight: 700; }}")
        except Exception as exc:
            QMessageBox.critical(root, "Emergency Stop Failed", str(exc))

    stop_btn.clicked.connect(_emergency_stop)

    root_layout.addWidget(sidebar)

    # ── Right side: content + status bar ──────────────────────────────────
    right_side = QWidget()
    right_layout = QVBoxLayout(right_side)
    right_layout.setContentsMargins(0, 0, 0, 0)
    right_layout.setSpacing(0)
    right_layout.addWidget(stacked)

    # Status bar
    status_bar = QWidget()
    status_bar.setObjectName("statusBar")
    status_bar.setFixedHeight(34)
    status_bar.setStyleSheet(_STATUS_BAR_STYLE)
    sb_layout = QHBoxLayout(status_bar)
    sb_layout.setContentsMargins(16, 4, 16, 4)
    sb_layout.setSpacing(16)

    online_dot = _make_status_dot(_SUCCESS)
    online_dot.setToolTip("Network status")
    session_lbl = QLabel("Session: —")
    session_lbl.setStyleSheet(_MUTED_LABEL)
    provider_lbl = QLabel("Provider: —")
    provider_lbl.setStyleSheet(_MUTED_LABEL)
    emotion_lbl = QLabel("Emotion: neutral")
    emotion_lbl.setStyleSheet(_MUTED_LABEL)
    token_bar = QProgressBar()
    token_bar.setRange(0, max(1, settings.DAILY_TOKEN_HARD_CAP or 500_000))
    token_bar.setValue(0)
    token_bar.setFixedWidth(140)
    token_bar.setFixedHeight(10)
    token_bar.setStyleSheet(_PROGRESS_STYLE)
    token_bar.setToolTip("Daily token usage")
    token_lbl = QLabel("0 / — tokens")
    token_lbl.setStyleSheet(_MUTED_LABEL)

    sb_layout.addWidget(online_dot)
    sb_layout.addWidget(session_lbl)
    sb_layout.addWidget(provider_lbl)
    sb_layout.addWidget(emotion_lbl)
    sb_layout.addStretch()
    sb_layout.addWidget(token_bar)
    sb_layout.addWidget(token_lbl)

    right_layout.addWidget(status_bar)
    root_layout.addWidget(right_side, stretch=1)

    # ── Status refresh ─────────────────────────────────────────────────────
    def _refresh_status() -> None:
        snap = build_status_snapshot(agent)
        online_dot.setStyleSheet(
            f"QLabel {{ color: {_SUCCESS if snap.get('online') else _ERROR}; font-size: 10px; background: transparent; }}"
        )
        session_lbl.setText(f"Session: {snap.get('session', '—')}")
        provider_lbl.setText(f"Provider: {snap.get('provider', '—')}")
        emotion_lbl.setText(f"Emotion: {snap.get('emotion', 'neutral')}")
        tday = snap.get("tokens_today", 0)
        cap = settings.DAILY_TOKEN_HARD_CAP or 500_000
        token_bar.setRange(0, max(1, cap))
        token_bar.setValue(min(tday, cap))
        pct = min(100, int(tday / cap * 100)) if cap else 0
        color = _ERROR if pct > 90 else _WARNING if pct > 70 else _ACCENT
        token_bar.setStyleSheet(_PROGRESS_STYLE + f"\nQProgressBar::chunk {{ background: {color}; border-radius: 6px; }}")
        token_lbl.setText(f"{tday:,} / {cap:,}")

    # ── PAGE 0: Chat ───────────────────────────────────────────────────────
    chat_page = QWidget()
    cp_layout = QVBoxLayout(chat_page)
    cp_layout.setContentsMargins(0, 0, 0, 0)
    cp_layout.setSpacing(0)

    # Chat header
    chat_header = QWidget()
    chat_header.setStyleSheet(f"QWidget {{ background: {_BG2}; border-bottom: 1px solid {_BORDER}; }}")
    ch_layout = QHBoxLayout(chat_header)
    ch_layout.setContentsMargins(16, 10, 16, 10)
    chat_title = QLabel("Chat")
    chat_title.setStyleSheet(_HEADER_LABEL)
    session_input = QLineEdit()
    session_input.setPlaceholderText("Switch session…")
    session_input.setFixedWidth(180)
    session_input.setStyleSheet(_INPUT_STYLE)
    switch_btn = QPushButton("Switch")
    switch_btn.setStyleSheet(_GHOST_BTN)
    switch_btn.setFixedHeight(32)
    export_btn = QPushButton("Export")
    export_btn.setStyleSheet(_GHOST_BTN)
    export_btn.setFixedHeight(32)
    mute_btn = QPushButton("Mute")
    mute_btn.setStyleSheet(_GHOST_BTN)
    mute_btn.setFixedHeight(32)
    privacy_combo = QComboBox()
    privacy_combo.addItems(["full_cloud", "balanced", "local_only"])
    privacy_combo.setFixedWidth(110)
    privacy_combo.setToolTip("Privacy mode")
    upload_btn = QPushButton("📎 Image")
    upload_btn.setStyleSheet(_GHOST_BTN)
    upload_btn.setFixedHeight(32)

    ch_layout.addWidget(chat_title)
    ch_layout.addStretch()
    ch_layout.addWidget(QLabel("Session:"))
    ch_layout.addWidget(session_input)
    ch_layout.addWidget(switch_btn)
    ch_layout.addWidget(privacy_combo)
    ch_layout.addWidget(mute_btn)
    ch_layout.addWidget(export_btn)
    ch_layout.addWidget(upload_btn)
    cp_layout.addWidget(chat_header)

    # Chat output
    chat_output = QTextEdit()
    chat_output.setReadOnly(True)
    chat_output.setStyleSheet(_CHAT_STYLE)
    cp_layout.addWidget(chat_output, stretch=1)

    # Chat input bar
    chat_input_bar = QWidget()
    chat_input_bar.setStyleSheet(f"QWidget {{ background: {_BG2}; border-top: 1px solid {_BORDER}; }}")
    cib_layout = QHBoxLayout(chat_input_bar)
    cib_layout.setContentsMargins(16, 10, 16, 10)
    cib_layout.setSpacing(8)
    chat_input = QLineEdit()
    chat_input.setPlaceholderText("Message NOVA…")
    chat_input.setStyleSheet(_INPUT_STYLE)
    chat_input.setFixedHeight(40)
    send_btn = QPushButton("Send")
    send_btn.setStyleSheet(_PRIMARY_BTN)
    send_btn.setFixedSize(80, 40)
    cib_layout.addWidget(chat_input, stretch=1)
    cib_layout.addWidget(send_btn)
    cp_layout.addWidget(chat_input_bar)
    stacked.addWidget(chat_page)

    def _append_chat(text: str) -> None:
        chat_output.append(text)

    def _stream_prompt(prompt: str, heading: str = "NOVA") -> None:
        _append_chat(f"<b style='color:{_ACCENT}'>{heading}:</b> ")
        def _worker() -> None:
            for token in agent.ask_stream(prompt):
                QTimer.singleShot(0, lambda t=token: chat_output.insertPlainText(t))
            provider = agent.last_provider_label()
            QTimer.singleShot(0, lambda: chat_output.append(
                f"<span style='color:{_TEXT3};font-size:11px'>[{provider}]</span><br>"
            ))
            QTimer.singleShot(0, _refresh_status)
        threading.Thread(target=_worker, daemon=True).start()

    def _send_message() -> None:
        text = chat_input.text().strip()
        if not text:
            return
        if len(text) > 50_000:
            _append_chat(f"<span style='color:{_WARNING}'>[system] Input too long.</span>")
            return
        _append_chat(f"<b style='color:{_ACCENT2}'>You:</b> {text}")
        chat_input.clear()
        _stream_prompt(text)

    def _switch_session() -> None:
        name = session_input.text().strip()
        if not name:
            return
        state = agent.switch_session(name)
        _append_chat(f"<span style='color:{_TEXT3}'>[system] switched to {state.name}</span>")
        _refresh_status()

    def _export_session() -> None:
        try:
            path = agent.export_session("md")
            _append_chat(f"<span style='color:{_SUCCESS}'>[export] → {path}</span>")
        except Exception as exc:
            _append_chat(f"<span style='color:{_ERROR}'>[error] {exc}</span>")

    def _toggle_mute() -> None:
        muted = agent.toggle_mute()
        mute_btn.setText("Unmute" if muted else "Mute")
        _refresh_status()

    def _change_privacy(idx: int) -> None:
        mode = privacy_combo.currentText()
        try:
            agent._set_session_privacy_mode(mode)
        except Exception:
            pass

    def _upload_image() -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            root, "Select Image", "", "Images (*.png *.jpg *.jpeg *.webp *.bmp)"
        )
        if not file_path:
            return
        try:
            with open(file_path, "rb") as f:
                img_bytes = f.read()
            analysis = analyze_image(img_bytes)
            _append_chat(f"<span style='color:{_ACCENT}'>[image]</span> {file_path}")
            prompt = f"User uploaded image. Analysis: {analysis}"
            _stream_prompt(prompt, heading="NOVA (image)")
        except Exception as exc:
            _append_chat(f"<span style='color:{_ERROR}'>[error] {exc}</span>")

    send_btn.clicked.connect(_send_message)
    chat_input.returnPressed.connect(_send_message)
    switch_btn.clicked.connect(_switch_session)
    export_btn.clicked.connect(_export_session)
    mute_btn.clicked.connect(_toggle_mute)
    upload_btn.clicked.connect(_upload_image)
    privacy_combo.currentIndexChanged.connect(_change_privacy)

    # ── PAGE 1: Voice ──────────────────────────────────────────────────────
    voice_page = QWidget()
    vp_main = QVBoxLayout(voice_page)
    vp_main.setContentsMargins(24, 24, 24, 24)
    vp_main.setSpacing(16)

    voice_title = QLabel("Voice Control")
    voice_title.setStyleSheet(_HEADER_LABEL)
    vp_main.addWidget(voice_title)

    # Mic card
    mic_card, mic_card_layout = _make_card(voice_page)
    mic_label = QLabel("Microphone")
    mic_label.setStyleSheet(_section_label("").styleSheet())
    mic_card_layout.addWidget(_section_label("MICROPHONE"))

    mic_btn = _build_mic_btn()
    mic_btn.setFixedHeight(44)
    voice_loop_btn = QPushButton("▶  Start Voice Loop")
    voice_loop_btn.setStyleSheet(_GHOST_BTN)
    voice_loop_btn.setFixedHeight(36)

    mic_row = QHBoxLayout()
    mic_row.addWidget(mic_btn)
    mic_row.addWidget(voice_loop_btn)
    mic_card_layout.addLayout(mic_row)
    vp_main.addWidget(mic_card)

    # Voice log
    voice_log_card, vlc_layout = _make_card(voice_page)
    vlc_layout.addWidget(_section_label("TRANSCRIPT LOG"))
    voice_log = QTextEdit()
    voice_log.setReadOnly(True)
    voice_log.setStyleSheet(_CHAT_STYLE + f"QTextEdit {{ min-height: 200px; border-radius: 8px; }}")
    vlc_layout.addWidget(voice_log)
    vp_main.addWidget(voice_log_card)

    # Key manager / model manager / voice settings
    tool_card, tool_layout = _make_card(voice_page)
    tool_layout.addWidget(_section_label("TOOLS"))
    tool_row = QHBoxLayout()
    key_btn = QPushButton("🔑  Key Manager")
    key_btn.setStyleSheet(_GHOST_BTN)
    model_btn = QPushButton("🧠  Model Manager")
    model_btn.setStyleSheet(_GHOST_BTN)
    voice_cfg_btn = QPushButton("🎚  Voice Settings")
    voice_cfg_btn.setStyleSheet(_GHOST_BTN)
    tool_row.addWidget(key_btn)
    tool_row.addWidget(model_btn)
    tool_row.addWidget(voice_cfg_btn)
    tool_layout.addLayout(tool_row)
    vp_main.addWidget(tool_card)
    vp_main.addStretch()
    stacked.addWidget(voice_page)

    def _voice_append(text: str) -> None:
        voice_log.append(text)

    def _mic_one_shot() -> None:
        if not mic_lock.acquire(blocking=False):
            _voice_append("<span style='color:orange'>[voice] already recording</span>")
            return
        mic_btn._start_anim()
        _voice_append("<span style='color:cyan'>[voice] listening…</span>")
        def _worker() -> None:
            try:
                from voice.stt import transcribe as stt_online
                from voice.stt_offline import OfflineWhisper
                from voice.vad import VADRecorder
                recorder = VADRecorder(silence_ms=settings.VAD_SILENCE_MS)
                audio = recorder.capture_until_silence()
                if not audio:
                    QTimer.singleShot(0, lambda: _voice_append("<span style='color:gray'>[voice] no speech</span>"))
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
                    QTimer.singleShot(0, lambda: _voice_append("<span style='color:gray'>[voice] empty transcription</span>"))
                    return
                def _submit() -> None:
                    _voice_append(f"<b style='color:{_ACCENT2}'>You (voice):</b> {text}")
                    _append_chat(f"<b style='color:{_ACCENT2}'>You (voice):</b> {text}")
                    _stream_prompt(text)
                QTimer.singleShot(0, _submit)
            except Exception as exc:
                QTimer.singleShot(0, lambda e=str(exc): _voice_append(f"<span style='color:{_ERROR}'>[error] {e}</span>"))
            finally:
                mic_lock.release()
                QTimer.singleShot(0, mic_btn._stop_anim)
        threading.Thread(target=_worker, daemon=True).start()

    def _toggle_voice_loop() -> None:
        thread = voice_loop_state.get("thread")
        if thread and thread.is_alive():
            stop_ev = voice_loop_state.get("stop_event")
            if stop_ev:
                stop_ev.set()
            _voice_append("<span style='color:orange'>[voice] stopping loop…</span>")
            voice_loop_btn.setText("▶  Start Voice Loop")
            return
        stop_ev = threading.Event()
        voice_loop_state["stop_event"] = stop_ev
        def _loop_worker() -> None:
            try:
                from interfaces.voice_interface import run_voice_loop
                run_voice_loop(agent, interactive_text_fallback=False,
                               use_wakeword=bool(getattr(settings, "has_wakeword", False)),
                               stop_event=stop_ev)
            except Exception as exc:
                QTimer.singleShot(0, lambda e=str(exc): _voice_append(f"<span style='color:{_ERROR}'>[error] {e}</span>"))
            finally:
                QTimer.singleShot(0, lambda: voice_loop_btn.setText("▶  Start Voice Loop"))
        voice_loop_state["thread"] = threading.Thread(target=_loop_worker, daemon=True)
        voice_loop_state["thread"].start()
        _voice_append("<span style='color:green'>[voice] loop started</span>")
        voice_loop_btn.setText("⏹  Stop Voice Loop")

    def _open_keys() -> None:
        try:
            from interfaces.key_manager import open_key_manager_dialog
            open_key_manager_dialog(settings_obj=settings, parent=root)
        except Exception as exc:
            _voice_append(f"<span style='color:{_ERROR}'>[error] {exc}</span>")

    def _open_models() -> None:
        try:
            from interfaces.model_manager import open_model_manager_dialog
            open_model_manager_dialog(agent, parent=root)
        except Exception as exc:
            _voice_append(f"<span style='color:{_ERROR}'>[error] {exc}</span>")

    def _open_voice_settings() -> None:
        try:
            from interfaces.voice_settings import open_voice_settings_dialog
            open_voice_settings_dialog(settings_obj=settings, parent=root)
        except Exception as exc:
            _voice_append(f"<span style='color:{_ERROR}'>[error] {exc}</span>")

    mic_btn.clicked.connect(_mic_one_shot)
    voice_loop_btn.clicked.connect(_toggle_voice_loop)
    key_btn.clicked.connect(_open_keys)
    model_btn.clicked.connect(_open_models)
    voice_cfg_btn.clicked.connect(_open_voice_settings)

    # ── PAGE 2: Autonomy ───────────────────────────────────────────────────
    auto_page = QWidget()
    ap_main = QVBoxLayout(auto_page)
    ap_main.setContentsMargins(24, 24, 24, 24)
    ap_main.setSpacing(16)

    auto_title = QLabel("Autonomy & Goals")
    auto_title.setStyleSheet(_HEADER_LABEL)
    ap_main.addWidget(auto_title)

    # Autonomy toggle card
    atog_card, atog_layout = _make_card(auto_page)
    atog_layout.addWidget(_section_label("AUTONOMY LOOP"))
    atog_row = QHBoxLayout()
    auto_toggle = QPushButton("Enable Autonomy" if not settings.AUTONOMY_ENABLED else "Disable Autonomy")
    auto_toggle.setStyleSheet(_PRIMARY_BTN if not settings.AUTONOMY_ENABLED else _DANGER_BTN)
    auto_toggle.setFixedHeight(36)
    auto_status_lbl = QLabel("Status: " + ("running" if settings.AUTONOMY_ENABLED else "stopped"))
    auto_status_lbl.setStyleSheet(_MUTED_LABEL)
    atog_row.addWidget(auto_toggle)
    atog_row.addWidget(auto_status_lbl)
    atog_row.addStretch()
    atog_layout.addLayout(atog_row)
    ap_main.addWidget(atog_card)

    def _toggle_autonomy() -> None:
        try:
            from config.nova_settings_manager import apply_setting
            enabled = settings.AUTONOMY_ENABLED
            new_val = not enabled
            apply_setting("AUTONOMY_ENABLED", new_val)
            if new_val:
                try:
                    agent._start_autonomy_loop()
                except Exception:
                    pass
                auto_toggle.setText("Disable Autonomy")
                auto_toggle.setStyleSheet(_DANGER_BTN)
                auto_status_lbl.setText("Status: running")
            else:
                try:
                    agent._stop_autonomy_loop()
                except Exception:
                    pass
                auto_toggle.setText("Enable Autonomy")
                auto_toggle.setStyleSheet(_PRIMARY_BTN)
                auto_status_lbl.setText("Status: stopped")
        except Exception as exc:
            QMessageBox.critical(root, "Error", str(exc))

    auto_toggle.clicked.connect(_toggle_autonomy)

    # Goal management card
    goal_card, goal_layout = _make_card(auto_page)
    goal_layout.addWidget(_section_label("GOALS"))
    goal_input_row = QHBoxLayout()
    goal_input = QLineEdit()
    goal_input.setPlaceholderText("Describe a goal for NOVA…")
    goal_add_btn = QPushButton("Add Goal")
    goal_add_btn.setStyleSheet(_PRIMARY_BTN)
    goal_add_btn.setFixedHeight(34)
    goal_input_row.addWidget(goal_input, stretch=1)
    goal_input_row.addWidget(goal_add_btn)
    goal_layout.addLayout(goal_input_row)

    goal_id_row = QHBoxLayout()
    goal_id_input = QLineEdit()
    goal_id_input.setPlaceholderText("goal-id for resume/cancel")
    goal_id_input.setFixedWidth(240)
    goal_resume_btn = QPushButton("Resume")
    goal_resume_btn.setStyleSheet(_GHOST_BTN)
    goal_cancel_btn = QPushButton("Cancel")
    goal_cancel_btn.setStyleSheet(_DANGER_BTN)
    goal_refresh_btn = QPushButton("↻")
    goal_refresh_btn.setStyleSheet(_GHOST_BTN)
    goal_refresh_btn.setFixedWidth(32)
    goal_id_row.addWidget(goal_id_input)
    goal_id_row.addWidget(goal_resume_btn)
    goal_id_row.addWidget(goal_cancel_btn)
    goal_id_row.addStretch()
    goal_id_row.addWidget(goal_refresh_btn)
    goal_layout.addLayout(goal_id_row)

    goal_output = QTextEdit()
    goal_output.setReadOnly(True)
    goal_output.setFixedHeight(180)
    goal_output.setStyleSheet(_CHAT_STYLE + "QTextEdit { border-radius: 8px; min-height: 80px; }")
    goal_layout.addWidget(goal_output)
    ap_main.addWidget(goal_card)

    # Mission card
    mission_card, mis_layout = _make_card(auto_page)
    mis_layout.addWidget(_section_label("MISSIONS"))
    mis_row1 = QHBoxLayout()
    mission_name_input = QLineEdit()
    mission_name_input.setPlaceholderText("name")
    mission_schedule_input = QLineEdit()
    mission_schedule_input.setPlaceholderText("schedule (e.g. every day at 08:00)")
    mission_goal_input = QLineEdit()
    mission_goal_input.setPlaceholderText("goal description")
    mis_row1.addWidget(mission_name_input)
    mis_row1.addWidget(mission_schedule_input)
    mis_row1.addWidget(mission_goal_input)
    mis_layout.addLayout(mis_row1)

    mis_row2 = QHBoxLayout()
    mission_target_input = QLineEdit()
    mission_target_input.setPlaceholderText("mission name for enable/disable/run")
    mission_add_btn = QPushButton("Add")
    mission_add_btn.setStyleSheet(_PRIMARY_BTN)
    mission_enable_btn = QPushButton("Enable")
    mission_enable_btn.setStyleSheet(_GHOST_BTN)
    mission_disable_btn = QPushButton("Disable")
    mission_disable_btn.setStyleSheet(_GHOST_BTN)
    mission_run_btn = QPushButton("Run Now")
    mission_run_btn.setStyleSheet(_GHOST_BTN)
    mission_list_btn = QPushButton("↻")
    mission_list_btn.setStyleSheet(_GHOST_BTN)
    mission_list_btn.setFixedWidth(32)
    mis_row2.addWidget(mission_target_input)
    mis_row2.addWidget(mission_add_btn)
    mis_row2.addWidget(mission_enable_btn)
    mis_row2.addWidget(mission_disable_btn)
    mis_row2.addWidget(mission_run_btn)
    mis_row2.addWidget(mission_list_btn)
    mis_layout.addLayout(mis_row2)

    mission_output = QTextEdit()
    mission_output.setReadOnly(True)
    mission_output.setFixedHeight(120)
    mission_output.setStyleSheet(_CHAT_STYLE + "QTextEdit { border-radius: 8px; }")
    mis_layout.addWidget(mission_output)
    ap_main.addWidget(mission_card)
    ap_main.addStretch()
    stacked.addWidget(auto_page)

    def _refresh_goals() -> None:
        try:
            goal_output.setPlainText(format_goal_list(agent.list_goals()))
        except Exception as exc:
            goal_output.setPlainText(f"Error: {exc}")

    def _add_goal() -> None:
        goal = goal_input.text().strip()
        if not goal:
            return
        try:
            result = agent.add_goal(goal)
            goal_output.append(f"[added] {result}")
            goal_input.clear()
            _refresh_goals()
        except Exception as exc:
            goal_output.append(f"[error] {exc}")

    def _resume_goal() -> None:
        gid = goal_id_input.text().strip()
        if not gid:
            return
        try:
            result = agent.resume_goal(gid)
            goal_output.append(f"[resumed] {result}")
            _refresh_goals()
        except Exception as exc:
            goal_output.append(f"[error] {exc}")

    def _cancel_goal() -> None:
        gid = goal_id_input.text().strip()
        if not gid:
            return
        try:
            result = agent.cancel_goal(gid)
            goal_output.append(f"[cancelled] {result}")
            _refresh_goals()
        except Exception as exc:
            goal_output.append(f"[error] {exc}")

    goal_add_btn.clicked.connect(_add_goal)
    goal_resume_btn.clicked.connect(_resume_goal)
    goal_cancel_btn.clicked.connect(_cancel_goal)
    goal_refresh_btn.clicked.connect(_refresh_goals)

    def _mission_target() -> str:
        return mission_target_input.text().strip() or mission_name_input.text().strip()

    def _add_mission() -> None:
        n = mission_name_input.text().strip()
        s = mission_schedule_input.text().strip()
        g = mission_goal_input.text().strip()
        if not (n and s and g):
            mission_output.append("[error] fill name, schedule, and goal")
            return
        try:
            result = agent._mission_add(n, s, g, True)
            mission_output.append(f"[added] {result}")
        except Exception as exc:
            mission_output.append(f"[error] {exc}")

    def _enable_mission() -> None:
        name = _mission_target()
        if not name:
            return
        try:
            mission_output.append(f"[enabled] {agent._mission_enable(name)}")
        except Exception as exc:
            mission_output.append(f"[error] {exc}")

    def _disable_mission() -> None:
        name = _mission_target()
        if not name:
            return
        try:
            mission_output.append(f"[disabled] {agent._mission_disable(name)}")
        except Exception as exc:
            mission_output.append(f"[error] {exc}")

    def _run_mission_now() -> None:
        name = _mission_target()
        if not name:
            return
        try:
            mission_output.append(f"[run] {agent._mission_run_now(name)}")
        except Exception as exc:
            mission_output.append(f"[error] {exc}")

    def _refresh_missions() -> None:
        try:
            payload = agent._mission_list()
            mission_output.setPlainText(json.dumps(payload, ensure_ascii=False, indent=2))
        except Exception as exc:
            mission_output.setPlainText(f"Error: {exc}")

    mission_add_btn.clicked.connect(_add_mission)
    mission_enable_btn.clicked.connect(_enable_mission)
    mission_disable_btn.clicked.connect(_disable_mission)
    mission_run_btn.clicked.connect(_run_mission_now)
    mission_list_btn.clicked.connect(_refresh_missions)

    # ── PAGE 3: Integrations ───────────────────────────────────────────────
    integ_page = QWidget()
    ip_scroll = QScrollArea()
    ip_scroll.setWidget(integ_page)
    ip_scroll.setWidgetResizable(True)
    ip_scroll.setStyleSheet("QScrollArea { border: none; }")
    ip_main = QVBoxLayout(integ_page)
    ip_main.setContentsMargins(24, 24, 24, 24)
    ip_main.setSpacing(16)

    integ_title = QLabel("Integrations")
    integ_title.setStyleSheet(_HEADER_LABEL)
    ip_main.addWidget(integ_title)

    # Health overview card
    health_card, hc_layout = _make_card(integ_page)
    hc_layout.addWidget(_section_label("SUBSYSTEM HEALTH"))
    health_output = QTextEdit()
    health_output.setReadOnly(True)
    health_output.setFixedHeight(160)
    health_output.setStyleSheet(_CHAT_STYLE + "QTextEdit { border-radius: 8px; }")
    health_refresh_btn = QPushButton("↻ Refresh Health")
    health_refresh_btn.setStyleSheet(_GHOST_BTN)
    health_refresh_btn.setFixedHeight(30)
    hc_layout.addWidget(health_output)
    hc_layout.addWidget(health_refresh_btn)
    ip_main.addWidget(health_card)

    # Events card
    events_card, ev_layout = _make_card(integ_page)
    ev_layout.addWidget(_section_label("RECENT EVENTS"))
    event_output = QTextEdit()
    event_output.setReadOnly(True)
    event_output.setFixedHeight(160)
    event_output.setStyleSheet(_CHAT_STYLE + "QTextEdit { border-radius: 8px; }")
    alert_refresh_btn = QPushButton("↻ Refresh Events")
    alert_refresh_btn.setStyleSheet(_GHOST_BTN)
    alert_refresh_btn.setFixedHeight(30)
    ev_layout.addWidget(event_output)
    ev_layout.addWidget(alert_refresh_btn)
    ip_main.addWidget(events_card)
    ip_main.addStretch()
    stacked.addWidget(ip_scroll)

    def _refresh_health() -> None:
        try:
            items = agent.health.status_table()
            summary = summarize_health(items)
            health_output.setPlainText(f"Summary: {summary}\n\n{format_health_table(items)}")
        except Exception as exc:
            health_output.setPlainText(f"Error: {exc}")

    def _refresh_events() -> None:
        try:
            events = agent.recent_events()
            event_output.setPlainText(format_event_log(events))
        except Exception as exc:
            event_output.setPlainText(f"Error: {exc}")

    health_refresh_btn.clicked.connect(_refresh_health)
    alert_refresh_btn.clicked.connect(_refresh_events)

    # ── PAGE 4: Settings ───────────────────────────────────────────────────
    settings_page = QWidget()
    sp_scroll = QScrollArea()
    sp_scroll.setWidget(settings_page)
    sp_scroll.setWidgetResizable(True)
    sp_scroll.setStyleSheet("QScrollArea { border: none; }")
    sp_main = QVBoxLayout(settings_page)
    sp_main.setContentsMargins(24, 24, 24, 24)
    sp_main.setSpacing(16)

    settings_title = QLabel("Settings")
    settings_title.setStyleSheet(_HEADER_LABEL)
    sp_main.addWidget(settings_title)

    try:
        from config.nova_settings_manager import schema_groups, apply_setting, settings_snapshot
        _snap = settings_snapshot(redact_secrets=False)

        for group in schema_groups():
            grp_card, grp_layout = _make_card(settings_page)
            grp_layout.addWidget(_section_label(group["label"].upper()))
            for s in group.get("settings", []):
                key = s["key"]
                typ = s.get("type", "str")
                current_val = _snap.get(key, s.get("default", ""))
                row = QHBoxLayout()
                lbl = QLabel(s.get("label", key))
                lbl.setFixedWidth(200)
                lbl.setToolTip(s.get("description", ""))
                lbl.setStyleSheet(_LABEL_STYLE)
                row.addWidget(lbl)
                if typ == "bool":
                    ctrl = QCheckBox()
                    ctrl.setChecked(bool(current_val))
                    ctrl.stateChanged.connect(lambda v, k=key: apply_setting(k, bool(v)))
                    row.addWidget(ctrl)
                elif typ == "choice":
                    ctrl = QComboBox()
                    ctrl.addItems(s.get("choices", []))
                    if str(current_val) in s.get("choices", []):
                        ctrl.setCurrentText(str(current_val))
                    ctrl.currentTextChanged.connect(lambda v, k=key: apply_setting(k, v))
                    row.addWidget(ctrl)
                else:
                    ctrl = QLineEdit()
                    ctrl.setText(str(current_val))
                    if s.get("secret"):
                        ctrl.setEchoMode(QLineEdit.EchoMode.Password)
                    ctrl.editingFinished.connect(lambda k=key, w=ctrl: apply_setting(k, w.text()))
                    row.addWidget(ctrl, stretch=1)
                row.addStretch()
                grp_layout.addLayout(row)
            sp_main.addWidget(grp_card)
    except Exception as exc:
        err_lbl = QLabel(f"Settings unavailable: {exc}")
        err_lbl.setStyleSheet(f"QLabel {{ color: {_ERROR}; }}")
        sp_main.addWidget(err_lbl)

    plugin_card, plg_layout = _make_card(settings_page)
    plg_layout.addWidget(_section_label("PLUGIN GENERATOR"))
    plugin_desc_input = QLineEdit()
    plugin_desc_input.setPlaceholderText("Describe a plugin to generate…")
    plugin_gen_btn = QPushButton("Generate Plugin")
    plugin_gen_btn.setStyleSheet(_GHOST_BTN)
    plg_row = QHBoxLayout()
    plg_row.addWidget(plugin_desc_input, stretch=1)
    plg_row.addWidget(plugin_gen_btn)
    plg_layout.addLayout(plg_row)
    sp_main.addWidget(plugin_card)
    sp_main.addStretch()
    stacked.addWidget(sp_scroll)

    def _generate_plugin() -> None:
        desc = plugin_desc_input.text().strip()
        if not desc:
            return
        gen = getattr(agent, "_plugin_generator", None)
        if gen is None:
            return
        try:
            result = gen.generate_and_propose(desc)
            plugin_desc_input.setPlaceholderText(f"Done: {result[:50]}…")
        except Exception as exc:
            plugin_desc_input.setPlaceholderText(f"Error: {exc}")

    plugin_gen_btn.clicked.connect(_generate_plugin)

    # ── PAGE 5: Profiles ───────────────────────────────────────────────────
    profile_page = QWidget()
    pp_main = QVBoxLayout(profile_page)
    pp_main.setContentsMargins(24, 24, 24, 24)
    pp_main.setSpacing(16)

    profile_title = QLabel("Settings Profiles")
    profile_title.setStyleSheet(_HEADER_LABEL)
    pp_main.addWidget(profile_title)

    prof_card, prof_layout = _make_card(profile_page)
    prof_layout.addWidget(_section_label("SAVE / LOAD PROFILE"))
    prof_row = QHBoxLayout()
    profile_name_input = QLineEdit()
    profile_name_input.setPlaceholderText("profile name…")
    profile_save_btn = QPushButton("Save Profile")
    profile_save_btn.setStyleSheet(_PRIMARY_BTN)
    prof_row.addWidget(profile_name_input, stretch=1)
    prof_row.addWidget(profile_save_btn)
    prof_layout.addLayout(prof_row)

    load_row = QHBoxLayout()
    profile_combo = QComboBox()
    profile_load_btn = QPushButton("Load")
    profile_load_btn.setStyleSheet(_GHOST_BTN)
    profile_delete_btn = QPushButton("Delete")
    profile_delete_btn.setStyleSheet(_DANGER_BTN)
    profile_refresh_btn = QPushButton("↻")
    profile_refresh_btn.setStyleSheet(_GHOST_BTN)
    profile_refresh_btn.setFixedWidth(32)
    load_row.addWidget(profile_combo, stretch=1)
    load_row.addWidget(profile_load_btn)
    load_row.addWidget(profile_delete_btn)
    load_row.addWidget(profile_refresh_btn)
    prof_layout.addLayout(load_row)

    profile_log = QTextEdit()
    profile_log.setReadOnly(True)
    profile_log.setFixedHeight(120)
    profile_log.setStyleSheet(_CHAT_STYLE + "QTextEdit { border-radius: 8px; }")
    prof_layout.addWidget(profile_log)
    pp_main.addWidget(prof_card)

    env_card, env_layout = _make_card(profile_page)
    env_layout.addWidget(_section_label("EXPORT SETTINGS"))
    env_export_btn = QPushButton("Export to .env Snippet")
    env_export_btn.setStyleSheet(_GHOST_BTN)
    env_output = QTextEdit()
    env_output.setReadOnly(True)
    env_output.setFixedHeight(200)
    env_output.setStyleSheet(_CHAT_STYLE + "QTextEdit { border-radius: 8px; }")
    env_layout.addWidget(env_export_btn)
    env_layout.addWidget(env_output)
    pp_main.addWidget(env_card)
    pp_main.addStretch()
    stacked.addWidget(profile_page)

    def _refresh_profiles() -> None:
        try:
            from config.nova_settings_manager import list_profiles
            profiles = list_profiles()
            profile_combo.clear()
            profile_combo.addItems(profiles)
        except Exception:
            pass

    def _save_profile() -> None:
        name = profile_name_input.text().strip()
        if not name:
            return
        try:
            from config.nova_settings_manager import save_profile
            result = save_profile(name)
            profile_log.append(f"<span style='color:{_SUCCESS}'>{result}</span>")
            _refresh_profiles()
        except Exception as exc:
            profile_log.append(f"<span style='color:{_ERROR}'>{exc}</span>")

    def _load_profile() -> None:
        name = profile_combo.currentText()
        if not name:
            return
        try:
            from config.nova_settings_manager import load_profile
            result = load_profile(name)
            profile_log.append(f"<span style='color:{_SUCCESS}'>{result}</span>")
        except Exception as exc:
            profile_log.append(f"<span style='color:{_ERROR}'>{exc}</span>")

    def _delete_profile() -> None:
        name = profile_combo.currentText()
        if not name:
            return
        try:
            from config.nova_settings_manager import delete_profile
            result = delete_profile(name)
            profile_log.append(f"<span style='color:{_WARNING}'>{result}</span>")
            _refresh_profiles()
        except Exception as exc:
            profile_log.append(f"<span style='color:{_ERROR}'>{exc}</span>")

    def _export_env() -> None:
        try:
            from config.nova_settings_manager import export_env_snippet
            snippet = export_env_snippet(include_secrets=False)
            env_output.setPlainText(snippet)
        except Exception as exc:
            env_output.setPlainText(f"Error: {exc}")

    profile_save_btn.clicked.connect(_save_profile)
    profile_load_btn.clicked.connect(_load_profile)
    profile_delete_btn.clicked.connect(_delete_profile)
    profile_refresh_btn.clicked.connect(_refresh_profiles)
    env_export_btn.clicked.connect(_export_env)
    _refresh_profiles()

    # ── PAGE 6: Debug ──────────────────────────────────────────────────────
    debug_page = QWidget()
    dp_scroll = QScrollArea()
    dp_scroll.setWidget(debug_page)
    dp_scroll.setWidgetResizable(True)
    dp_scroll.setStyleSheet("QScrollArea { border: none; }")
    dp_main = QVBoxLayout(debug_page)
    dp_main.setContentsMargins(24, 24, 24, 24)
    dp_main.setSpacing(16)

    debug_title = QLabel("Debug & Services")
    debug_title.setStyleSheet(_HEADER_LABEL)
    dp_main.addWidget(debug_title)

    # Ollama card
    ollama_card, oll_layout = _make_card(debug_page)
    oll_layout.addWidget(_section_label("OLLAMA"))
    oll_row = QHBoxLayout()
    ollama_dot = _make_status_dot(_TEXT3)
    ollama_lbl = QLabel("Checking…")
    ollama_lbl.setStyleSheet(_MUTED_LABEL)
    ollama_models_lbl = QLabel("")
    ollama_models_lbl.setStyleSheet(_MUTED_LABEL)
    oll_start_btn = QPushButton("Start Ollama")
    oll_start_btn.setStyleSheet(_GHOST_BTN)
    oll_start_btn.setFixedHeight(30)
    oll_refresh_btn = QPushButton("↻")
    oll_refresh_btn.setStyleSheet(_GHOST_BTN)
    oll_refresh_btn.setFixedWidth(32)
    oll_refresh_btn.setFixedHeight(30)
    oll_row.addWidget(ollama_dot)
    oll_row.addWidget(ollama_lbl)
    oll_row.addWidget(ollama_models_lbl)
    oll_row.addStretch()
    oll_row.addWidget(oll_start_btn)
    oll_row.addWidget(oll_refresh_btn)
    oll_layout.addLayout(oll_row)
    dp_main.addWidget(ollama_card)

    # OmniParser card
    omni_card, omni_layout = _make_card(debug_page)
    omni_layout.addWidget(_section_label("OMNIPARSER"))
    omni_row = QHBoxLayout()
    omni_dot = _make_status_dot(_TEXT3)
    omni_lbl = QLabel("Checking…")
    omni_lbl.setStyleSheet(_MUTED_LABEL)
    omni_start_btn = QPushButton("Start OmniParser")
    omni_start_btn.setStyleSheet(_GHOST_BTN)
    omni_start_btn.setFixedHeight(30)
    omni_refresh_btn = QPushButton("↻")
    omni_refresh_btn.setStyleSheet(_GHOST_BTN)
    omni_refresh_btn.setFixedWidth(32)
    omni_refresh_btn.setFixedHeight(30)
    omni_row.addWidget(omni_dot)
    omni_row.addWidget(omni_lbl)
    omni_row.addStretch()
    omni_row.addWidget(omni_start_btn)
    omni_row.addWidget(omni_refresh_btn)
    omni_layout.addLayout(omni_row)
    dp_main.addWidget(omni_card)

    # Status JSON card
    dbg_card, dbg_layout = _make_card(debug_page)
    dbg_layout.addWidget(_section_label("STATUS JSON"))
    status_btn = QPushButton("Load Status JSON")
    status_btn.setStyleSheet(_GHOST_BTN)
    status_btn.setFixedHeight(30)
    debug_output = QTextEdit()
    debug_output.setReadOnly(True)
    debug_output.setFixedHeight(320)
    debug_output.setStyleSheet(_CHAT_STYLE + "QTextEdit { border-radius: 8px; font-family: monospace; font-size: 12px; }")
    dbg_layout.addWidget(status_btn)
    dbg_layout.addWidget(debug_output)
    dp_main.addWidget(dbg_card)
    dp_main.addStretch()
    stacked.addWidget(dp_scroll)

    def _refresh_ollama() -> None:
        def _probe() -> None:
            try:
                from utils.service_health import check_ollama
                result = check_ollama(settings.OLLAMA_BASE_URL)
            except Exception as exc:
                result = {"status": "down", "latency_ms": None, "models": [], "error": str(exc)}
            _svc_health["ollama"] = result
            color = _SUCCESS if result["status"] == "ok" else _WARNING if result["status"] == "degraded" else _ERROR
            models_txt = ", ".join(result.get("models", [])[:5]) or "—"
            latency = result.get("latency_ms")
            lbl_txt = f"{result['status'].upper()}  {f'({latency}ms)' if latency else ''}"
            def _update():
                ollama_dot.setStyleSheet(f"QLabel {{ color: {color}; font-size: 10px; background: transparent; }}")
                ollama_lbl.setText(lbl_txt)
                ollama_models_lbl.setText(f"Models: {models_txt}")
            QTimer.singleShot(0, _update)
        threading.Thread(target=_probe, daemon=True).start()

    def _refresh_omni() -> None:
        def _probe() -> None:
            try:
                from utils.service_health import check_omniparser
                result = check_omniparser(settings.OMNIPARSER_SERVER_URL)
            except Exception as exc:
                result = {"status": "down", "latency_ms": None, "error": str(exc)}
            _svc_health["omniparser"] = result
            color = _SUCCESS if result["status"] == "ok" else _ERROR
            latency = result.get("latency_ms")
            lbl_txt = f"{result['status'].upper()}  {f'({latency}ms)' if latency else ''}"
            def _update():
                omni_dot.setStyleSheet(f"QLabel {{ color: {color}; font-size: 10px; background: transparent; }}")
                omni_lbl.setText(lbl_txt)
            QTimer.singleShot(0, _update)
        threading.Thread(target=_probe, daemon=True).start()

    def _start_ollama() -> None:
        def _run() -> None:
            try:
                from utils.service_health import start_ollama_serve
                msg = start_ollama_serve()
                QTimer.singleShot(0, lambda: debug_output.append(f"[ollama] {msg}"))
                QTimer.singleShot(2000, _refresh_ollama)
            except Exception as exc:
                QTimer.singleShot(0, lambda e=str(exc): debug_output.append(f"[error] {e}"))
        threading.Thread(target=_run, daemon=True).start()

    def _start_omniparser() -> None:
        try:
            agent.omniparser.start()
            debug_output.append("[omniparser] start requested")
            QTimer.singleShot(3000, _refresh_omni)
        except Exception as exc:
            debug_output.append(f"[error] {exc}")

    def _show_status_json() -> None:
        try:
            debug_output.setPlainText(agent.status_text())
        except Exception as exc:
            debug_output.setPlainText(f"Error: {exc}")

    oll_refresh_btn.clicked.connect(_refresh_ollama)
    oll_start_btn.clicked.connect(_start_ollama)
    omni_refresh_btn.clicked.connect(_refresh_omni)
    omni_start_btn.clicked.connect(_start_omniparser)
    status_btn.clicked.connect(_show_status_json)

    # ── Global timer ───────────────────────────────────────────────────────
    main_timer = QTimer()

    def _tick() -> None:
        _refresh_status()

    main_timer.timeout.connect(_tick)
    main_timer.start(3_000)

    svc_timer = QTimer()

    def _svc_tick() -> None:
        _refresh_ollama()
        _refresh_omni()

    svc_timer.timeout.connect(_svc_tick)
    svc_timer.start(30_000)

    # ── Boot refreshes ─────────────────────────────────────────────────────
    _refresh_status()
    _refresh_goals()
    _refresh_missions()
    _refresh_events()
    _refresh_health()
    _refresh_ollama()
    _refresh_omni()

    # Wire health into Ollama auto-start
    def _boot_check_ollama() -> None:
        try:
            from utils.service_health import ensure_ollama_running
            msg = ensure_ollama_running(settings.OLLAMA_BASE_URL)
            if msg != "ok":
                _append_chat(f"<span style='color:{_WARNING}'>[boot] Ollama: {msg}</span>")
        except Exception:
            pass
    threading.Thread(target=_boot_check_ollama, daemon=True).start()

    # ── Final assembly ─────────────────────────────────────────────────────
    _switch_page(0)
    nav_buttons[0].setProperty("active", "true")

    root.resize(1280, 860)
    root.setMinimumSize(900, 600)
    root.show()
    app.exec()
