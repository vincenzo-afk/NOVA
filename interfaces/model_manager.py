"""Model manager UI for Ollama and cloud provider snapshots."""

from __future__ import annotations

import json
import subprocess
import threading
import time
from typing import Any


def _run(cmd: list[str], timeout: float = 20.0) -> str:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return out.stdout.strip()
    except Exception:
        return ""


def list_ollama_models() -> list[dict[str, Any]]:
    # Newer Ollama versions support JSON output.
    raw_json = _run(["ollama", "list", "--json"], timeout=12.0)
    if raw_json:
        try:
            payload = json.loads(raw_json)
            if isinstance(payload, list):
                return payload
            if isinstance(payload, dict) and isinstance(payload.get("models"), list):
                return payload["models"]
        except Exception:
            pass

    raw = _run(["ollama", "list"], timeout=12.0)
    rows: list[dict[str, Any]] = []
    for line in raw.splitlines()[1:]:
        parts = [p for p in line.split("  ") if p.strip()]
        if not parts:
            continue
        name = parts[0].strip()
        size = parts[-2].strip() if len(parts) >= 2 else ""
        modified = parts[-1].strip() if len(parts) >= 3 else ""
        rows.append({"name": name, "size": size, "modified": modified})
    return rows


def pull_ollama_model(model_name: str, on_output: callable | None = None) -> dict[str, Any]:
    model = (model_name or "").strip()
    if not model:
        return {"status": "error", "reason": "model_required"}
    try:
        proc = subprocess.Popen(
            ["ollama", "pull", model],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
    except Exception as exc:
        return {"status": "error", "reason": f"spawn_failed:{exc}"}

    lines: list[str] = []
    assert proc.stdout is not None
    for line in proc.stdout:
        stripped = line.rstrip("\n")
        if stripped:
            lines.append(stripped)
            if on_output is not None:
                try:
                    on_output(stripped)
                except Exception:
                    pass
    code = proc.wait()
    return {"status": "ok" if code == 0 else "error", "exit_code": code, "log": lines[-50:]}


def delete_ollama_model(model_name: str) -> dict[str, Any]:
    model = (model_name or "").strip()
    if not model:
        return {"status": "error", "reason": "model_required"}
    try:
        out = subprocess.run(["ollama", "rm", model], capture_output=True, text=True, timeout=20.0)
        return {
            "status": "ok" if out.returncode == 0 else "error",
            "exit_code": out.returncode,
            "stdout": out.stdout.strip(),
            "stderr": out.stderr.strip(),
        }
    except Exception as exc:
        return {"status": "error", "reason": f"delete_failed:{exc}"}


def benchmark_providers(agent: Any, prompt: str = "Reply with the word: ready") -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    # Local benchmark
    try:
        start = time.time()
        with agent.engine.local_only_mode(True):
            out = agent.engine.ask(prompt=prompt, system="You are a test responder.", history=[])
        duration = max(0.001, time.time() - start)
        rows.append(
            {
                "provider": "local_ollama",
                "ok": bool(out.strip()),
                "latency_s": round(duration, 3),
                "chars_per_s": round(len(out) / duration, 2),
            }
        )
    except Exception as exc:
        rows.append({"provider": "local_ollama", "ok": False, "reason": str(exc)})

    # Cloud benchmark if available
    try:
        start = time.time()
        with agent.engine.local_only_mode(False):
            out = agent.engine.ask(prompt=prompt, system="You are a test responder.", history=[])
        provider = str(agent.engine.last_provider)
        duration = max(0.001, time.time() - start)
        rows.append(
            {
                "provider": provider or "cloud",
                "ok": bool(out.strip()),
                "latency_s": round(duration, 3),
                "chars_per_s": round(len(out) / duration, 2),
            }
        )
    except Exception as exc:
        rows.append({"provider": "cloud", "ok": False, "reason": str(exc)})

    return rows


def open_model_manager_dialog(agent: Any, parent: Any = None) -> None:
    try:
        from PyQt6.QtCore import QTimer
        from PyQt6.QtWidgets import (
            QDialog,
            QHBoxLayout,
            QInputDialog,
            QLabel,
            QListWidget,
            QMessageBox,
            QPushButton,
            QTextEdit,
            QVBoxLayout,
        )
    except Exception:
        return

    dlg = QDialog(parent)
    dlg.setWindowTitle("NOVA Model Manager")
    root = QVBoxLayout()
    models = QListWidget()
    output = QTextEdit()
    output.setReadOnly(True)

    row = QHBoxLayout()
    refresh_btn = QPushButton("Refresh")
    pull_btn = QPushButton("Pull")
    delete_btn = QPushButton("Delete")
    benchmark_btn = QPushButton("Benchmark")
    row.addWidget(refresh_btn)
    row.addWidget(pull_btn)
    row.addWidget(delete_btn)
    row.addWidget(benchmark_btn)

    root.addWidget(QLabel("Installed Ollama Models"))
    root.addWidget(models)
    root.addLayout(row)
    root.addWidget(QLabel("Output"))
    root.addWidget(output)
    dlg.setLayout(root)

    def refresh() -> None:
        models.clear()
        try:
            data = list_ollama_models()
            for item in data:
                name = str(item.get("name") or item.get("model") or "")
                size = str(item.get("size") or "")
                modified = str(item.get("modified") or item.get("modified_at") or "")
                models.addItem(f"{name}  |  {size}  |  {modified}")
            output.append(f"Loaded {len(data)} models.")
        except Exception as exc:
            output.append(f"Refresh failed: {exc}")

    def pull_model() -> None:
        name, ok = QInputDialog.getText(dlg, "Pull Model", "Model name (e.g. llama3.1:8b):")
        if not ok or not str(name).strip():
            return
        output.append(f"Pulling {name} ...")

        def worker() -> None:
            result = pull_ollama_model(str(name), on_output=lambda line: QTimer.singleShot(0, lambda l=line: output.append(l)))
            QTimer.singleShot(0, lambda: output.append(str(result)))
            QTimer.singleShot(0, refresh)

        threading.Thread(target=worker, daemon=True).start()

    def delete_model() -> None:
        item = models.currentItem()
        if item is None:
            QMessageBox.information(dlg, "Model Manager", "Select a model first.")
            return
        model_name = item.text().split("|", 1)[0].strip()
        yes = QMessageBox.question(dlg, "Confirm Delete", f"Delete model '{model_name}'?")
        if yes != QMessageBox.StandardButton.Yes:
            return
        result = delete_ollama_model(model_name)
        output.append(str(result))
        refresh()

    def run_benchmark() -> None:
        output.append("Running benchmark ...")

        def worker() -> None:
            rows = benchmark_providers(agent)
            QTimer.singleShot(0, lambda: output.append(json.dumps(rows, ensure_ascii=False, indent=2)))
            try:
                snap = agent.engine.provider_snapshot()
                QTimer.singleShot(0, lambda: output.append("Key pool snapshot:\n" + json.dumps(snap, ensure_ascii=False, indent=2)))
            except Exception:
                pass

        threading.Thread(target=worker, daemon=True).start()

    refresh_btn.clicked.connect(refresh)
    pull_btn.clicked.connect(pull_model)
    delete_btn.clicked.connect(delete_model)
    benchmark_btn.clicked.connect(run_benchmark)

    dlg.resize(860, 560)
    refresh()
    dlg.exec()
