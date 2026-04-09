"""Self-writing plugin generator — Feature 8.

Security model (read carefully before modifying):
  1. The LLM generates plugin source code.
  2. The code MUST pass _check_ast() from core/plugin_loader.py.
  3. The code is shown to the user, who MUST explicitly approve it.
  4. Only after approval is the .py file written to plugins/.
  5. The plugin is then loaded through the normal load_plugins() path,
     which applies _check_ast() again plus _restricted_import() at exec time.

This double-gate (AST check + human approval + runtime sandbox) ensures
LLM-generated code cannot bypass the sandbox automatically.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger(__name__)

_PLUGIN_DIR = Path("plugins")
_PENDING_DIR = Path(".jarvis/pending_plugins")

_SYSTEM_PROMPT = """\
You are a plugin code generator for NOVA, an autonomous AI assistant.

Generate a single Python plugin file that defines:
  PLUGIN_TOOLS = [
      {
          "name": "tool_name",
          "description": "what it does",
          "args": {"arg1": "description", "arg2": "description"},
          "fn": "function_name",
      },
  ]

  def function_name(arg1: str, arg2: str = "") -> dict:
      ...return...

Rules (ALL are mandatory — violations will be rejected):
- Do NOT import os, subprocess, socket, sys, requests, urllib, pathlib,
  io, tempfile, shutil, importlib, ctypes, threading, multiprocessing,
  signal, gc, weakref, builtins, or any module starting with _.
- Do NOT use eval, exec, compile, getattr, setattr, delattr, vars,
  locals, globals, dir, hasattr, __import__, __class__, __mro__,
  __subclasses__, __globals__, or __builtins__.
- Keep the code minimal and focused on the requested task.
- Return only the Python source code (no markdown fences, no explanation).
"""


class PluginGenerationError(RuntimeError):
    pass


class PluginGenerator:
    """Generates, validates, and (with user approval) hot-loads NOVA plugins."""

    def __init__(
        self,
        llm_callable: Callable[[str, str], str],
        dispatcher,
        confirm_callback: Callable[[str, str], bool] | None = None,
        scan_code_callback: Callable[[str, str], dict[str, Any]] | None = None,
    ):
        """
        Args:
            llm_callable: fn(system_prompt, user_prompt) → generated_code_str
            dispatcher: NOVAApp's Dispatcher instance
            confirm_callback: fn(tool_code, description) → bool.
                If None, always requires CLI confirmation.
        """
        self._llm = llm_callable
        self._dispatcher = dispatcher
        self._confirm = confirm_callback or _default_confirm
        self._scan_code = scan_code_callback

    def generate_and_propose(self, description: str) -> dict[str, Any]:
        """Full pipeline: generate → validate → show to user → approve → save → load.

        Returns a result dict describing the outcome.
        """
        log.info("[plugin_generator] Generating plugin for: %s", description)

        # 1. Generate code
        try:
            code = self._llm(_SYSTEM_PROMPT, description).strip()
        except Exception as exc:
            raise PluginGenerationError(f"LLM call failed: {exc}") from exc

        # Strip accidental markdown fences
        code = re.sub(r"^```(?:python)?\n?", "", code, flags=re.MULTILINE)
        code = re.sub(r"\n?```$", "", code, flags=re.MULTILINE)
        code = code.strip()

        if not code:
            raise PluginGenerationError("LLM returned empty code.")

        # Optional malware/suspicious-content scan before AST and file writes.
        if self._scan_code is not None:
            try:
                scan = self._scan_code(code, "generated_plugin.py")
                if isinstance(scan, dict) and not scan.get("safe", True):
                    raise PluginGenerationError(f"Generated code blocked by scanner: {scan}")
            except PluginGenerationError:
                raise
            except Exception as exc:
                log.warning("[plugin_generator] scanner failed (continuing cautiously): %s", exc)

        # 2. AST validation (first gate)
        try:
            from core.plugin_loader import _check_ast
            _check_ast(code)
        except Exception as exc:
            log.warning("[plugin_generator] AST check failed: %s", exc)
            raise PluginGenerationError(f"Generated code failed AST safety check: {exc}") from exc

        log.info("[plugin_generator] AST check passed.")

        # Save to pending dir for inspection
        _PENDING_DIR.mkdir(parents=True, exist_ok=True)
        code_hash = hashlib.sha256(code.encode()).hexdigest()[:12]
        pending_path = _PENDING_DIR / f"pending_{code_hash}.py"
        pending_path.write_text(code, encoding="utf-8")

        # 3. Human approval (mandatory — this gate CANNOT be bypassed)
        approved = self._confirm(code, description)
        if not approved:
            log.info("[plugin_generator] Plugin rejected by user.")
            pending_path.unlink(missing_ok=True)
            return {"status": "rejected", "reason": "user_declined"}

        # 4. Write to plugins/ directory
        slug = re.sub(r"[^a-z0-9_]", "_", description.lower())[:32].strip("_")
        plugin_name = f"gen_{slug}_{code_hash[:6]}"
        plugin_path = _PLUGIN_DIR / f"{plugin_name}.py"
        _PLUGIN_DIR.mkdir(exist_ok=True)
        plugin_path.write_text(code, encoding="utf-8")
        pending_path.unlink(missing_ok=True)
        log.info("[plugin_generator] Plugin written to %s", plugin_path)

        # 5. Hot-load through the normal sandboxed loader (second gate)
        try:
            from core.plugin_loader import load_plugins
            newly_loaded = load_plugins(self._dispatcher, plugin_dir=str(_PLUGIN_DIR))
            log.info("[plugin_generator] Hot-loaded: %s", newly_loaded)
        except Exception as exc:
            log.error("[plugin_generator] Hot-load failed: %s", exc)
            return {
                "status": "error",
                "reason": f"hot_load_failed: {exc}",
                "plugin_path": str(plugin_path),
            }

        return {
            "status": "loaded",
            "plugin_path": str(plugin_path),
            "plugin_name": plugin_name,
            "loaded_files": newly_loaded,
        }


def _cli_confirm(code: str, description: str) -> bool:
    """Default human-approval callback using the terminal."""
    separator = "─" * 60
    print(f"\n{separator}")
    print(f"  NOVA Plugin Generator — Review Required")
    print(f"  Task: {description}")
    print(separator)
    print(code)
    print(separator)
    try:
        ans = input("  Approve and load this plugin? [y/N]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        ans = "n"
    return ans.startswith("y")


def _default_confirm(code: str, description: str) -> bool:
    gui_decision = _gui_confirm(code, description)
    if gui_decision is not None:
        return gui_decision
    if threading.current_thread() is threading.main_thread() and sys.stdin and sys.stdin.isatty():
        return _cli_confirm(code, description)
    return False


def _gui_confirm(code: str, description: str) -> bool | None:
    try:
        from PyQt6.QtWidgets import (
            QApplication,
            QDialog,
            QHBoxLayout,
            QLabel,
            QPushButton,
            QTextEdit,
            QVBoxLayout,
        )
    except Exception:
        return None

    app = QApplication.instance()
    if app is None:
        return None
    if threading.current_thread() is not threading.main_thread():
        return None

    dialog = QDialog()
    dialog.setWindowTitle("NOVA Plugin Approval")
    root = QVBoxLayout()
    root.addWidget(QLabel(f"Task: {description}"))

    code_box = QTextEdit()
    code_box.setReadOnly(True)
    code_box.setPlainText(code)
    root.addWidget(code_box)

    actions = QHBoxLayout()
    approve_btn = QPushButton("Approve")
    reject_btn = QPushButton("Reject")
    actions.addWidget(approve_btn)
    actions.addWidget(reject_btn)
    root.addLayout(actions)
    dialog.setLayout(root)

    state = {"approved": False}

    def _approve() -> None:
        state["approved"] = True
        dialog.accept()

    def _reject() -> None:
        state["approved"] = False
        dialog.reject()

    approve_btn.clicked.connect(_approve)
    reject_btn.clicked.connect(_reject)
    dialog.resize(960, 680)
    dialog.exec()
    return bool(state["approved"])
