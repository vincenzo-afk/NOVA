"""Model manager UI for Ollama and cloud provider snapshots."""

from __future__ import annotations

import json
import subprocess
import threading
import time
from typing import Any

from config.settings import settings
from core.llm.roundrobin import RoundRobinPool
from interfaces.key_manager import test_provider_key


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


def provider_key_snapshot(agent: Any) -> dict[str, Any]:
    try:
        raw = agent.engine.provider_snapshot()
    except Exception:
        return {"cloud": [], "active_count": 0, "status_counts": {}}

    cloud_rows: list[dict[str, Any]]
    if isinstance(raw, list):
        cloud_rows = [row for row in raw if isinstance(row, dict)]
        active_count = sum(1 for row in cloud_rows if row.get("status") == "active")
    elif isinstance(raw, dict):
        cloud_rows = [row for row in (raw.get("cloud") or raw.get("keys") or []) if isinstance(row, dict)]
        active_count = int(raw.get("active_count", 0))
    else:
        cloud_rows = []
        active_count = 0

    status_counts: dict[str, int] = {}
    for row in cloud_rows:
        status = str(row.get("status", "unknown"))
        status_counts[status] = status_counts.get(status, 0) + 1

    return {"cloud": cloud_rows, "active_count": active_count, "status_counts": status_counts}


def recommend_provider(agent: Any, benchmark_rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    rows = benchmark_rows if benchmark_rows is not None else benchmark_providers(agent)
    candidates = [row for row in rows if isinstance(row, dict) and row.get("ok")]
    if not candidates:
        return {"recommended": "none", "reason": "no_successful_candidates", "candidates": rows}

    snapshot = provider_key_snapshot(agent)
    active_cloud = int(snapshot.get("active_count", 0))
    rate_limited = int((snapshot.get("status_counts") or {}).get("rate_limited", 0))

    profiler = getattr(agent, "_tool_profiler", None)
    aggregate_success = 1.0
    aggregate_tool_latency_ms = 0.0
    try:
        stats = profiler.all_stats() if profiler else {}
        if isinstance(stats, dict) and stats:
            totals = []
            latencies = []
            for _, item in stats.items():
                if not isinstance(item, dict):
                    continue
                succ = int(item.get("success", 0))
                fail = int(item.get("failure", 0))
                total = max(1, succ + fail)
                totals.append((succ, total))
                latencies.append(float(item.get("avg_latency_ms", 0.0) or 0.0))
            if totals:
                succ_sum = sum(s for s, _ in totals)
                total_sum = sum(t for _, t in totals)
                aggregate_success = succ_sum / max(1, total_sum)
            if latencies:
                aggregate_tool_latency_ms = sum(latencies) / len(latencies)
    except Exception:
        pass

    scored: list[tuple[float, dict[str, Any]]] = []
    for row in candidates:
        latency = float(row.get("latency_s", 9999.0) or 9999.0)
        provider = str(row.get("provider", "unknown")).lower()
        penalty = 0.0
        if "cloud" in provider and active_cloud <= 0:
            penalty += 3.0
        if "cloud" in provider and rate_limited > 0:
            penalty += min(2.0, 0.35 * rate_limited)
        if aggregate_success < 0.75 and "cloud" in provider:
            penalty += 0.4
        if aggregate_tool_latency_ms > 1400 and "local" in provider:
            penalty -= 0.15
        scored.append((latency + penalty, row))

    scored.sort(key=lambda x: x[0])
    best_score, best = scored[0]
    return {
        "recommended": best.get("provider"),
        "score": round(best_score, 3),
        "active_cloud_keys": active_cloud,
        "rate_limited_cloud_keys": rate_limited,
        "toolchain_success_rate": round(aggregate_success, 3),
        "toolchain_avg_latency_ms": round(aggregate_tool_latency_ms, 1),
        "candidates": candidates,
    }


def add_runtime_key(agent: Any, provider: str, key: str) -> dict[str, Any]:
    p = (provider or "").strip().lower()
    value = (key or "").strip()
    if not value:
        return {"status": "error", "reason": "key_required"}

    if p == "openai":
        keys = list(getattr(settings, "OPENAI_API_KEYS", []) or [])
        keys.append(value)
        settings.OPENAI_API_KEYS = keys
        agent.engine.pool = RoundRobinPool(keys) if keys else None
        return {"status": "ok", "provider": "openai", "count": len(keys)}
    if p == "gemini":
        keys = list(getattr(settings, "GEMINI_API_KEYS", []) or [])
        keys.append(value)
        settings.GEMINI_API_KEYS = keys
        return {"status": "ok", "provider": "gemini", "count": len(keys)}
    return {"status": "error", "reason": "runtime_add_supported_for_openai_or_gemini_only"}


def remove_runtime_key(agent: Any, provider: str, index_1_based: int) -> dict[str, Any]:
    p = (provider or "").strip().lower()
    idx = int(index_1_based) - 1
    if idx < 0:
        return {"status": "error", "reason": "invalid_index"}

    if p == "openai":
        keys = list(getattr(settings, "OPENAI_API_KEYS", []) or [])
        if idx >= len(keys):
            return {"status": "error", "reason": "index_out_of_range"}
        keys.pop(idx)
        settings.OPENAI_API_KEYS = keys
        agent.engine.pool = RoundRobinPool(keys) if keys else None
        return {"status": "ok", "provider": "openai", "count": len(keys)}
    if p == "gemini":
        keys = list(getattr(settings, "GEMINI_API_KEYS", []) or [])
        if idx >= len(keys):
            return {"status": "error", "reason": "index_out_of_range"}
        keys.pop(idx)
        settings.GEMINI_API_KEYS = keys
        return {"status": "ok", "provider": "gemini", "count": len(keys)}
    return {"status": "error", "reason": "runtime_remove_supported_for_openai_or_gemini_only"}


def open_model_manager_dialog(agent: Any, parent: Any = None) -> None:
    try:
        from PyQt6.QtCore import QTimer
        from PyQt6.QtWidgets import (
            QComboBox,
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
    key_list = QListWidget()
    output = QTextEdit()
    output.setReadOnly(True)

    row = QHBoxLayout()
    refresh_btn = QPushButton("Refresh")
    pull_btn = QPushButton("Pull")
    delete_btn = QPushButton("Delete")
    benchmark_btn = QPushButton("Benchmark")
    recommend_btn = QPushButton("Recommend")
    row.addWidget(refresh_btn)
    row.addWidget(pull_btn)
    row.addWidget(delete_btn)
    row.addWidget(benchmark_btn)
    row.addWidget(recommend_btn)

    key_row = QHBoxLayout()
    key_provider = QComboBox()
    key_provider.addItems(["openai", "gemini", "groq", "cerebras"])
    add_key_btn = QPushButton("Add Runtime Key")
    remove_key_btn = QPushButton("Remove Runtime Key")
    test_key_btn = QPushButton("Test Pasted Key")
    open_key_mgr_btn = QPushButton("Open Key Manager")
    key_row.addWidget(key_provider)
    key_row.addWidget(add_key_btn)
    key_row.addWidget(remove_key_btn)
    key_row.addWidget(test_key_btn)
    key_row.addWidget(open_key_mgr_btn)

    root.addWidget(QLabel("Installed Ollama Models"))
    root.addWidget(models)
    root.addLayout(row)
    root.addWidget(QLabel("Cloud Key Pool (runtime health)"))
    root.addWidget(key_list)
    root.addLayout(key_row)
    root.addWidget(QLabel("Output"))
    root.addWidget(output)
    dlg.setLayout(root)

    def refresh() -> None:
        models.clear()
        key_list.clear()
        try:
            data = list_ollama_models()
            for item in data:
                name = str(item.get("name") or item.get("model") or "")
                size = str(item.get("size") or "")
                modified = str(item.get("modified") or item.get("modified_at") or "")
                models.addItem(f"{name}  |  {size}  |  {modified}")
            output.append(f"Loaded {len(data)} models.")
            snap = provider_key_snapshot(agent)
            for row in snap.get("cloud", []):
                key_label = str(row.get("key", "key"))
                status = str(row.get("status", "unknown"))
                failures = int(row.get("failures", 0) or 0)
                cd = str(row.get("cooldown_until", "") or "")
                key_list.addItem(f"openai:{key_label}  [{status}] failures={failures} cooldown={cd}")
            output.append(
                "Cloud key health: "
                + json.dumps(
                    {
                        "active_count": snap.get("active_count", 0),
                        "status_counts": snap.get("status_counts", {}),
                    },
                    ensure_ascii=False,
                )
            )
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
                snap = provider_key_snapshot(agent)
                QTimer.singleShot(
                    0, lambda: output.append("Key pool snapshot:\n" + json.dumps(snap, ensure_ascii=False, indent=2))
                )
            except Exception:
                pass
            rec = recommend_provider(agent, benchmark_rows=rows)
            QTimer.singleShot(0, lambda: output.append("Recommendation:\n" + json.dumps(rec, ensure_ascii=False, indent=2)))

        threading.Thread(target=worker, daemon=True).start()

    def run_recommend() -> None:
        rec = recommend_provider(agent)
        output.append("Recommendation:\n" + json.dumps(rec, ensure_ascii=False, indent=2))

    def add_key() -> None:
        provider = key_provider.currentText().strip().lower()
        key, ok = QInputDialog.getText(dlg, "Add Runtime Key", f"{provider} key:")
        if not ok or not str(key).strip():
            return
        result = add_runtime_key(agent, provider, str(key).strip())
        output.append(str(result))
        refresh()

    def remove_key() -> None:
        item = key_list.currentItem()
        if item is None:
            QMessageBox.information(dlg, "Model Manager", "Select a cloud key row first.")
            return
        text = item.text().strip()
        # format: openai:key_1  [status] ...
        provider_part = text.split("  ", 1)[0]
        if ":" not in provider_part:
            QMessageBox.warning(dlg, "Model Manager", "Cannot parse selected key row.")
            return
        provider, label = provider_part.split(":", 1)
        if "_" not in label:
            QMessageBox.warning(dlg, "Model Manager", "Cannot parse selected key label.")
            return
        try:
            idx = int(label.rsplit("_", 1)[1])
        except Exception:
            QMessageBox.warning(dlg, "Model Manager", "Cannot parse selected key index.")
            return
        yes = QMessageBox.question(dlg, "Confirm Remove", f"Remove runtime key {provider}:{label}?")
        if yes != QMessageBox.StandardButton.Yes:
            return
        result = remove_runtime_key(agent, provider, idx)
        output.append(str(result))
        refresh()

    def test_pasted_key() -> None:
        provider = key_provider.currentText().strip().lower()
        value, ok = QInputDialog.getText(dlg, "Test Key", f"Paste {provider} key:")
        if not ok or not str(value).strip():
            return
        result = test_provider_key(provider, str(value).strip(), openai_base_url=getattr(settings, "OPENAI_BASE_URL", ""))
        output.append("Key test:\n" + json.dumps(result, ensure_ascii=False, indent=2))

    def open_key_manager() -> None:
        try:
            from interfaces.key_manager import open_key_manager_dialog

            open_key_manager_dialog(settings_obj=settings, parent=dlg)
        except Exception as exc:
            output.append(f"Key manager unavailable: {exc}")

    refresh_btn.clicked.connect(refresh)
    pull_btn.clicked.connect(pull_model)
    delete_btn.clicked.connect(delete_model)
    benchmark_btn.clicked.connect(run_benchmark)
    recommend_btn.clicked.connect(run_recommend)
    add_key_btn.clicked.connect(add_key)
    remove_key_btn.clicked.connect(remove_key)
    test_key_btn.clicked.connect(test_pasted_key)
    open_key_mgr_btn.clicked.connect(open_key_manager)

    dlg.resize(960, 680)
    refresh()
    dlg.exec()
