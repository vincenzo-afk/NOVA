"""BYOK encrypted key manager."""

from __future__ import annotations

import base64
import hashlib
import os
import time
from pathlib import Path
from typing import Any

import requests

_KEYSTORE_PATH = Path(".jarvis/keystore.enc")
_PBKDF2_ITERATIONS = 390_000
_PROVIDERS = [
    "openai",
    "gemini",
    "groq",
    "cerebras",
    "anthropic",
    "mem0",
    "telegram",
    "porcupine",
    "virustotal",
]


def _mask_key(key: str) -> str:
    cleaned = (key or "").strip()
    if len(cleaned) <= 10:
        return "*" * max(4, len(cleaned))
    return f"{cleaned[:4]}...{cleaned[-6:]}"


def _build_fernet(password: str, salt: bytes):
    from cryptography.fernet import Fernet

    raw = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS, dklen=32)
    token = base64.urlsafe_b64encode(raw)
    return Fernet(token)


class EncryptedKeyStore:
    def __init__(self, path: str | Path = _KEYSTORE_PATH):
        self.path = Path(path)

    def load(self, password: str) -> dict[str, list[str]]:
        if not self.path.exists():
            return {}
        try:
            import json
            from cryptography.fernet import InvalidToken
        except Exception as exc:
            raise RuntimeError("cryptography package required for key manager") from exc

        payload = json.loads(self.path.read_text(encoding="utf-8"))
        salt = base64.b64decode(payload["salt"])
        ciphertext = payload["ciphertext"].encode("utf-8")
        try:
            plain = _build_fernet(password, salt).decrypt(ciphertext)
        except InvalidToken as exc:
            raise RuntimeError("Invalid key manager password") from exc
        data = json.loads(plain.decode("utf-8"))
        out: dict[str, list[str]] = {}
        for provider, keys in data.items():
            if isinstance(keys, list):
                clean = [str(item).strip() for item in keys if str(item).strip()]
                if clean:
                    out[str(provider).strip().lower()] = clean
        return out

    def save(self, password: str, data: dict[str, list[str]]) -> None:
        try:
            import json
            import tempfile
        except Exception as exc:
            raise RuntimeError("json module unavailable") from exc
        self.path.parent.mkdir(parents=True, exist_ok=True)
        salt = os.urandom(16)
        clean: dict[str, list[str]] = {}
        for provider, keys in data.items():
            p = str(provider).strip().lower()
            if not p:
                continue
            values = [str(item).strip() for item in keys if str(item).strip()]
            if values:
                clean[p] = values
        plaintext = json.dumps(clean, ensure_ascii=False).encode("utf-8")
        ciphertext = _build_fernet(password, salt).encrypt(plaintext).decode("utf-8")
        wrapper = {
            "version": 1,
            "salt": base64.b64encode(salt).decode("ascii"),
            "ciphertext": ciphertext,
            "updated_at": int(time.time()),
        }
        payload = json.dumps(wrapper, ensure_ascii=False, indent=2)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(self.path.parent),
            delete=False,
            suffix=".tmp",
        ) as tmp:
            tmp.write(payload)
            tmp.flush()
            tmp_path = Path(tmp.name)
        tmp_path.replace(self.path)
        try:
            self.path.chmod(0o600)
        except Exception:
            pass

    def list_masked(self, password: str) -> dict[str, list[str]]:
        loaded = self.load(password)
        return {provider: [_mask_key(k) for k in keys] for provider, keys in loaded.items()}


def test_provider_key(provider: str, key: str, *, openai_base_url: str = "https://api.openai.com") -> dict[str, Any]:
    p = (provider or "").strip().lower()
    token = (key or "").strip()
    if not token:
        return {"ok": False, "reason": "empty_key"}
    started = time.time()

    try:
        if p == "openai":
            url = f"{openai_base_url.rstrip('/')}/v1/models"
            r = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=8)
            return {"ok": r.ok, "status_code": r.status_code, "latency_ms": int((time.time() - started) * 1000)}
        if p == "gemini":
            url = f"https://generativelanguage.googleapis.com/v1beta/models?key={token}"
            r = requests.get(url, timeout=8)
            return {"ok": r.ok, "status_code": r.status_code, "latency_ms": int((time.time() - started) * 1000)}
        if p == "groq":
            r = requests.get(
                "https://api.groq.com/openai/v1/models",
                headers={"Authorization": f"Bearer {token}"},
                timeout=8,
            )
            return {"ok": r.ok, "status_code": r.status_code, "latency_ms": int((time.time() - started) * 1000)}
        if p == "cerebras":
            r = requests.get(
                "https://api.cerebras.ai/v1/models",
                headers={"Authorization": f"Bearer {token}"},
                timeout=8,
            )
            return {"ok": r.ok, "status_code": r.status_code, "latency_ms": int((time.time() - started) * 1000)}
        if p == "telegram":
            r = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=8)
            return {"ok": r.ok, "status_code": r.status_code, "latency_ms": int((time.time() - started) * 1000)}
        if p == "virustotal":
            r = requests.get(
                "https://www.virustotal.com/api/v3/users/current",
                headers={"x-apikey": token},
                timeout=8,
            )
            return {"ok": r.ok, "status_code": r.status_code, "latency_ms": int((time.time() - started) * 1000)}
    except Exception as exc:
        return {"ok": False, "reason": f"request_error:{exc}"}

    return {"ok": False, "reason": "provider_test_not_implemented"}


def summarize_env_keys(settings_obj: Any) -> dict[str, list[str]]:
    summary: dict[str, list[str]] = {}
    openai = [k for k in getattr(settings_obj, "OPENAI_API_KEYS", []) if str(k).strip()]
    gemini = [k for k in getattr(settings_obj, "GEMINI_API_KEYS", []) if str(k).strip()]
    if openai:
        summary["openai"] = [_mask_key(k) for k in openai]
    if gemini:
        summary["gemini"] = [_mask_key(k) for k in gemini]
    for key_name, provider in [
        ("MEM0_API_KEY", "mem0"),
        ("TELEGRAM_BOT_TOKEN", "telegram"),
        ("PORCUPINE_ACCESS_KEY", "porcupine"),
        ("VIRUSTOTAL_API_KEY", "virustotal"),
    ]:
        val = str(getattr(settings_obj, key_name, "") or "").strip()
        if val:
            summary[provider] = [_mask_key(val)]
    return summary


def open_key_manager_dialog(settings_obj: Any, parent: Any = None) -> None:
    try:
        from PyQt6.QtWidgets import (
            QComboBox,
            QDialog,
            QGridLayout,
            QHBoxLayout,
            QInputDialog,
            QLabel,
            QLineEdit,
            QListWidget,
            QMessageBox,
            QPushButton,
            QVBoxLayout,
        )
    except Exception:
        return

    store = EncryptedKeyStore()
    data: dict[str, list[str]] = {}
    master_password: str = ""

    dlg = QDialog(parent)
    dlg.setWindowTitle("NOVA Key Manager")
    root = QVBoxLayout()

    top = QGridLayout()
    password_input = QLineEdit()
    password_input.setEchoMode(QLineEdit.EchoMode.Password)
    unlock_btn = QPushButton("Unlock")
    top.addWidget(QLabel("Master Password"), 0, 0)
    top.addWidget(password_input, 0, 1)
    top.addWidget(unlock_btn, 0, 2)
    root.addLayout(top)

    key_list = QListWidget()
    root.addWidget(key_list)

    row = QHBoxLayout()
    provider_combo = QComboBox()
    provider_combo.addItems(_PROVIDERS)
    key_input = QLineEdit()
    key_input.setPlaceholderText("Paste API key")
    row.addWidget(provider_combo)
    row.addWidget(key_input)
    root.addLayout(row)

    actions = QHBoxLayout()
    add_btn = QPushButton("Add")
    remove_btn = QPushButton("Remove Selected")
    test_btn = QPushButton("Test Key")
    save_btn = QPushButton("Save")
    actions.addWidget(add_btn)
    actions.addWidget(remove_btn)
    actions.addWidget(test_btn)
    actions.addWidget(save_btn)
    root.addLayout(actions)
    dlg.setLayout(root)

    def refresh_list() -> None:
        key_list.clear()
        for provider in sorted(data.keys()):
            keys = data.get(provider, [])
            for idx, key in enumerate(keys, start=1):
                key_list.addItem(f"{provider}:{idx}  {_mask_key(key)}")

    def unlock() -> None:
        nonlocal data, master_password
        pwd = password_input.text().strip()
        if not pwd:
            QMessageBox.warning(dlg, "Key Manager", "Master password required.")
            return
        master_password = pwd
        try:
            data = store.load(master_password)
        except Exception as exc:
            # If file doesn't exist yet, start fresh and allow save.
            if store.path.exists():
                QMessageBox.warning(dlg, "Key Manager", f"Unlock failed: {exc}")
                return
            data = {}
        refresh_list()

    def add_key() -> None:
        provider = provider_combo.currentText().strip().lower()
        value = key_input.text().strip()
        if not provider or not value:
            return
        data.setdefault(provider, []).append(value)
        key_input.clear()
        refresh_list()

    def remove_selected() -> None:
        item = key_list.currentItem()
        if item is None:
            return
        text = item.text()
        try:
            left, _masked = text.split("  ", 1)
            provider, idx_text = left.split(":", 1)
            idx = int(idx_text) - 1
            keys = data.get(provider, [])
            if 0 <= idx < len(keys):
                keys.pop(idx)
                if not keys:
                    data.pop(provider, None)
        except Exception:
            pass
        refresh_list()

    def test_key() -> None:
        provider = provider_combo.currentText().strip().lower()
        value = key_input.text().strip()
        if not value:
            QMessageBox.information(dlg, "Key Manager", "Paste a key first to test.")
            return
        result = test_provider_key(provider, value, openai_base_url=getattr(settings_obj, "OPENAI_BASE_URL", ""))
        QMessageBox.information(dlg, "Key Test", str(result))

    def save_keys() -> None:
        nonlocal master_password
        if not master_password:
            pwd, ok = QInputDialog.getText(
                dlg,
                "Master Password",
                "Set master password:",
                QLineEdit.EchoMode.Password,
            )
            if not ok:
                return
            master_password = str(pwd).strip()
        if not master_password:
            QMessageBox.warning(dlg, "Key Manager", "Master password is required.")
            return
        try:
            store.save(master_password, data)
            QMessageBox.information(dlg, "Key Manager", f"Saved encrypted keys to {store.path}")
        except Exception as exc:
            QMessageBox.warning(dlg, "Key Manager", f"Save failed: {exc}")

    unlock_btn.clicked.connect(unlock)
    add_btn.clicked.connect(add_key)
    remove_btn.clicked.connect(remove_selected)
    test_btn.clicked.connect(test_key)
    save_btn.clicked.connect(save_keys)
    dlg.resize(760, 460)
    dlg.exec()
