"""Self-learning automation manager for Phase 14 feature rollout."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import threading
import time
from typing import Any, Callable

@dataclass
class BatchJob:
    id: str
    kind: str
    payload: dict[str, Any]
    created_at: float
    status: str = "queued"
    attempts: int = 0
    last_error: str = ""


class AutomationFactory:
    def __init__(
        self,
        *,
        plugin_generate_fn: Callable[[str], dict[str, Any]],
        schedule_every_fn: Callable[[str, str, str], dict[str, Any]],
        notify_tts_fn: Callable[[str], bool],
        vision_analyze_fn: Callable[[bytes], dict[str, Any]],
        record_event_fn: Callable[[str, str], None],
        queue_path: str = ".jarvis/automation_batch_jobs.json",
        plugin_dir: str = "plugins",
    ) -> None:
        self._plugin_generate = plugin_generate_fn
        self._schedule_every = schedule_every_fn
        self._notify_tts = notify_tts_fn
        self._vision_analyze = vision_analyze_fn
        self._record_event = record_event_fn
        self._queue_path = Path(queue_path)
        self._queue_path.parent.mkdir(parents=True, exist_ok=True)
        self._plugin_dir = Path(plugin_dir)
        self._plugin_dir.mkdir(parents=True, exist_ok=True)
        self._jobs: list[BatchJob] = []
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._worker_thread: threading.Thread | None = None
        self._fail_counters: dict[str, int] = defaultdict(int)
        self._load_jobs()

    # ---------- High-level feature entry points ----------

    def learn_skill(self, skill_name: str) -> dict[str, Any]:
        docs = self._collect_docs(f"{skill_name} official documentation developer guide")
        file_path = self._write_skill_plugin(skill_name=skill_name, docs=docs)
        prompt = (
            f"Create a NOVA control plugin scaffold for {skill_name}. "
            "Expose tools to open app, navigate core actions, and provide a safe dry-run mode. "
            "Use pure Python and return deterministic dict outputs for each tool. "
            f"Reference summary:\n{docs['summary']}"
        )
        result = self._plugin_generate(prompt)
        return {
            "status": "ok",
            "feature": "skill_learner",
            "skill": skill_name,
            "docs": docs,
            "plugin": result,
            "scaffold_path": str(file_path),
        }

    def api_autodiscovery(self, api_name: str) -> dict[str, Any]:
        docs = self._collect_docs(f"{api_name} API documentation endpoints authentication examples")
        endpoints = self._extract_endpoints_from_summary(docs.get("summary", ""))
        file_path = self._write_api_plugin(api_name=api_name, docs=docs, endpoints=endpoints)
        prompt = (
            f"Generate a NOVA plugin client for {api_name} API. "
            "Create tools for authenticate, list core resources, and a health check call. "
            "Do not hardcode secrets. Accept api_key/tool args. "
            f"Extracted context:\n{docs['summary']}"
        )
        result = self._plugin_generate(prompt)
        return {
            "status": "ok",
            "feature": "api_autodiscovery",
            "api": api_name,
            "docs": docs,
            "endpoints": endpoints,
            "plugin": result,
            "scaffold_path": str(file_path),
        }

    def game_bot_generator(self, game_name: str) -> dict[str, Any]:
        file_path = self._write_game_bot_plugin(game_name=game_name)
        prompt = (
            f"Generate a NOVA game bot plugin for {game_name}. "
            "Implement a strategy helper tool that takes board_state text and returns best next move. "
            "Include a vision_parse placeholder tool input schema for OCR/grid extraction."
        )
        result = self._plugin_generate(prompt)
        return {"status": "ok", "feature": "game_bot_generator", "game": game_name, "plugin": result, "scaffold_path": str(file_path)}

    def app_reverse_engineer(self, app_name: str) -> dict[str, Any]:
        file_path = self._write_app_plugin(app_name=app_name)
        prompt = (
            f"Generate a NOVA UI-control plugin scaffold for {app_name}. "
            "Include tools: discover_windows, click_named_element, type_text, run_macro. "
            "Return robust errors when UI element is missing."
        )
        result = self._plugin_generate(prompt)
        return {"status": "ok", "feature": "app_reverse_engineer", "app": app_name, "plugin": result, "scaffold_path": str(file_path)}

    def live_data_feed_builder(self, topic: str, *, interval_minutes: int = 5) -> dict[str, Any]:
        docs = self._collect_docs(f"{topic} live scores API JSON endpoint")
        endpoints = self._extract_endpoints_from_summary(docs.get("summary", ""))
        file_path = self._write_live_feed_plugin(topic=topic, docs=docs, endpoints=endpoints)
        prompt = (
            f"Generate a NOVA live feed plugin for {topic}. "
            "Include a tool that fetches latest updates and returns only changed items from prior poll. "
            f"Docs context:\n{docs['summary']}"
        )
        plugin_result = self._plugin_generate(prompt)
        schedule = f"every {max(1, int(interval_minutes))} minutes"
        mission_name = _slug(f"live_{topic}")[:48] or "live_feed"
        mission_goal = f"Use latest {topic} tools and announce only score changes in concise text."
        job_result = self._schedule_every(mission_name, schedule, mission_goal)
        return {
            "status": "ok",
            "feature": "live_data_feed_builder",
            "topic": topic,
            "docs": docs,
            "endpoints": endpoints,
            "plugin": plugin_result,
            "scaffold_path": str(file_path),
            "mission": job_result,
        }

    def smart_home_discoverer(self) -> dict[str, Any]:
        scan = self._scan_lan_devices()
        stubs = self._write_device_plugin_stubs(scan.get("devices", []))
        return {"status": "ok", "feature": "smart_home_discoverer", "scan": scan, "stubs": stubs}

    def enqueue_batch_api_plugins(self, api_names: list[str]) -> dict[str, Any]:
        added: list[str] = []
        with self._lock:
            for name in api_names:
                clean = str(name).strip()
                if not clean:
                    continue
                jid = f"batch_{int(time.time() * 1000)}_{_slug(clean)[:24]}"
                self._jobs.append(
                    BatchJob(
                        id=jid,
                        kind="api_autodiscovery",
                        payload={"api_name": clean},
                        created_at=time.time(),
                    )
                )
                added.append(jid)
            self._persist_jobs()
            self._ensure_worker_locked()
        return {"status": "ok", "queued": len(added), "job_ids": added}

    def batch_status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "count": len(self._jobs),
                "jobs": [
                    {
                        "id": j.id,
                        "kind": j.kind,
                        "status": j.status,
                        "attempts": j.attempts,
                        "last_error": j.last_error,
                    }
                    for j in self._jobs[-50:]
                ],
            }

    def record_failure_and_recover(self, step_key: str, screenshot_path: str = "") -> dict[str, Any]:
        key = (step_key or "").strip().lower() or "unknown_step"
        self._fail_counters[key] += 1
        count = self._fail_counters[key]
        if count < 2:
            return {"status": "ok", "step": key, "failures": count, "recovery_triggered": False}

        vision = {}
        if screenshot_path:
            try:
                image_bytes = Path(screenshot_path).read_bytes()
                vision = self._vision_analyze(image_bytes)
            except Exception as exc:
                vision = {"error": f"screenshot_read_failed: {exc}"}
        prompt = (
            "Generate a targeted NOVA recovery plugin for repeated step failure. "
            f"Step key: {key}. Vision context: {json.dumps(vision, ensure_ascii=False)}. "
            "Plugin should add a precheck and one fallback strategy."
        )
        file_path = self._write_recovery_plugin(step_key=key, vision=vision)
        plugin = self._plugin_generate(prompt)
        self._record_event("recovery", f"Auto-recovery proposal generated for {key}")
        return {
            "status": "ok",
            "step": key,
            "failures": count,
            "recovery_triggered": True,
            "plugin": plugin,
            "vision": vision,
            "scaffold_path": str(file_path),
        }

    def context_mode_writer(self, context_label: str) -> dict[str, Any]:
        file_path = self._write_mode_plugin(context_label=context_label)
        prompt = (
            f"Generate a NOVA mode plugin for context '{context_label}'. "
            "Expose apply_mode and status tools. Mode should adjust verbosity, alerts, and autonomy behavior."
        )
        plugin = self._plugin_generate(prompt)
        return {
            "status": "ok",
            "feature": "context_mode_writer",
            "context": context_label,
            "plugin": plugin,
            "scaffold_path": str(file_path),
        }

    # ---------- worker ----------

    def stop(self) -> None:
        self._stop_event.set()
        with self._lock:
            thread = self._worker_thread
        if thread and thread.is_alive():
            thread.join(timeout=1.0)

    def _ensure_worker_locked(self) -> None:
        if self._worker_thread and self._worker_thread.is_alive():
            return
        self._stop_event.clear()
        self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker_thread.start()

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            job = self._next_job()
            if job is None:
                time.sleep(1.0)
                continue
            self._run_job(job)

    def _next_job(self) -> BatchJob | None:
        with self._lock:
            for j in self._jobs:
                if j.status == "queued":
                    j.status = "running"
                    self._persist_jobs()
                    return j
        return None

    def _run_job(self, job: BatchJob) -> None:
        try:
            job.attempts += 1
            if job.kind == "api_autodiscovery":
                api_name = str(job.payload.get("api_name", "")).strip()
                self.api_autodiscovery(api_name)
            else:
                raise ValueError(f"unsupported_job_kind:{job.kind}")
            with self._lock:
                job.status = "done"
                self._persist_jobs()
        except Exception as exc:
            with self._lock:
                job.status = "failed"
                job.last_error = str(exc)
                self._persist_jobs()

    # ---------- helpers ----------

    def _collect_docs(self, query: str, max_sources: int = 3) -> dict[str, Any]:
        try:
            from web.search import search as _search
            hits = _search(query, max_results=max(1, max_sources))
        except Exception:
            hits = []
        sources: list[dict[str, str]] = []
        snippets: list[str] = []
        for item in hits[:max_sources]:
            href = str(item.get("href", "")).strip()
            title = str(item.get("title", "")).strip()
            if not href:
                continue
            try:
                from web.scraper import scrape_text as _scrape_text

                text = _scrape_text(href)
                cleaned = re.sub(r"\s+", " ", text).strip()[:2500]
            except Exception:
                cleaned = ""
            sources.append({"title": title, "url": href})
            if cleaned:
                snippets.append(f"SOURCE: {title}\nURL: {href}\nTEXT: {cleaned}\n")
        summary = "\n\n".join(snippets)[:7000]
        return {"query": query, "sources": sources, "summary": summary}

    @staticmethod
    def _extract_endpoints_from_summary(summary: str) -> list[str]:
        text = str(summary or "")
        found = re.findall(r"(https?://[^\s\"')]+|/[a-zA-Z0-9_\-./{}:]+)", text)
        unique: list[str] = []
        seen = set()
        for item in found:
            value = item.strip().rstrip(".,;")
            if len(value) < 2:
                continue
            if value in seen:
                continue
            seen.add(value)
            unique.append(value)
        return unique[:25]

    def _write_skill_plugin(self, *, skill_name: str, docs: dict[str, Any]) -> Path:
        slug = _slug(skill_name) or "skill"
        path = self._plugin_dir / f"{slug}_control.py"
        summary = str(docs.get("summary", "")).replace('"""', "'''")[:1200]
        source = f'''"""Auto-generated skill control scaffold for {skill_name}."""

PLUGIN_TOOLS = [
    {{
        "name": "{slug}.open",
        "description": "Open {skill_name} and bring focus.",
        "args": {{"target": "window or workspace name"}},
        "fn": "open_target",
    }},
    {{
        "name": "{slug}.action",
        "description": "Run a named action in {skill_name}.",
        "args": {{"action": "action name", "value": "optional value"}},
        "fn": "run_action",
    }},
]

DOC_SUMMARY = """{summary}"""


def open_target(target: str = "") -> dict:
    return {{"status": "stub", "skill": "{skill_name}", "op": "open", "target": target}}


def run_action(action: str, value: str = "") -> dict:
    return {{"status": "stub", "skill": "{skill_name}", "op": "action", "action": action, "value": value}}
'''
        return self._write_plugin_file(path, source)

    def _write_api_plugin(self, *, api_name: str, docs: dict[str, Any], endpoints: list[str]) -> Path:
        slug = _slug(api_name) or "api"
        path = self._plugin_dir / f"{slug}_api_client.py"
        endpoint_block = "\n".join(f'    "{e}",' for e in (endpoints or ["/health"]))
        summary = str(docs.get("summary", "")).replace('"""', "'''")[:1200]
        source = f'''"""Auto-generated API client scaffold for {api_name}."""

try:
    import requests
except Exception:  # pragma: no cover
    requests = None

BASE_URL = ""
KNOWN_ENDPOINTS = [
{endpoint_block}
]
DOC_SUMMARY = """{summary}"""

PLUGIN_TOOLS = [
    {{
        "name": "{slug}.endpoints",
        "description": "List autodiscovered API endpoints.",
        "args": {{}},
        "fn": "list_endpoints",
    }},
    {{
        "name": "{slug}.call",
        "description": "Call an endpoint path using GET.",
        "args": {{"endpoint": "path or url", "api_key": "api key", "base_url": "optional base url"}},
        "fn": "call_endpoint",
    }},
]


def list_endpoints() -> dict:
    return {{"status": "ok", "api": "{api_name}", "endpoints": KNOWN_ENDPOINTS}}


def call_endpoint(endpoint: str, api_key: str = "", base_url: str = "") -> dict:
    if requests is None:
        return {{"status": "error", "reason": "requests_not_available"}}
    target = endpoint.strip()
    if target.startswith("/"):
        root = (base_url or BASE_URL).rstrip("/")
        if not root:
            return {{"status": "error", "reason": "base_url_required_for_relative_endpoint", "endpoint": target}}
        target = root + target
    headers = {{"Authorization": f"Bearer {{api_key}}"}} if api_key else {{}}
    try:
        resp = requests.get(target, timeout=20, headers=headers)
        body = resp.text[:1500]
        return {{"status": "ok", "code": resp.status_code, "url": target, "body_preview": body}}
    except Exception as exc:
        return {{"status": "error", "reason": str(exc), "url": target}}
'''
        return self._write_plugin_file(path, source)

    def _write_game_bot_plugin(self, *, game_name: str) -> Path:
        slug = _slug(game_name) or "game"
        path = self._plugin_dir / f"{slug}_bot.py"
        source = f'''"""Auto-generated game bot scaffold for {game_name}."""

PLUGIN_TOOLS = [
    {{
        "name": "{slug}.vision_parse",
        "description": "Parse board text into structured state.",
        "args": {{"board_text": "raw OCR text"}},
        "fn": "vision_parse",
    }},
    {{
        "name": "{slug}.best_move",
        "description": "Choose best next move from parsed board state.",
        "args": {{"board_state": "json or compact state"}},
        "fn": "best_move",
    }},
]


def vision_parse(board_text: str) -> dict:
    return {{"status": "stub", "game": "{game_name}", "board_text_len": len(board_text or "")}}


def best_move(board_state: str) -> dict:
    # Lightweight default strategy placeholder.
    move_order = ["up", "left", "right", "down"]
    idx = len(board_state or "") % len(move_order)
    return {{"status": "ok", "game": "{game_name}", "move": move_order[idx]}}
'''
        return self._write_plugin_file(path, source)

    def _write_app_plugin(self, *, app_name: str) -> Path:
        slug = _slug(app_name) or "app"
        path = self._plugin_dir / f"{slug}_control.py"
        source = f'''"""Auto-generated app reverse-engineering scaffold for {app_name}."""

PLUGIN_TOOLS = [
    {{
        "name": "{slug}.observe",
        "description": "Record observed UI interactions summary.",
        "args": {{"duration_seconds": "how long to observe (default 120)"}},
        "fn": "observe",
    }},
    {{
        "name": "{slug}.run_macro",
        "description": "Execute a named inferred macro.",
        "args": {{"macro": "macro name"}},
        "fn": "run_macro",
    }},
]


def observe(duration_seconds: int = 120) -> dict:
    return {{"status": "stub", "app": "{app_name}", "observed_for_seconds": max(1, int(duration_seconds))}}


def run_macro(macro: str) -> dict:
    return {{"status": "stub", "app": "{app_name}", "macro": macro}}
'''
        return self._write_plugin_file(path, source)

    def _write_live_feed_plugin(self, *, topic: str, docs: dict[str, Any], endpoints: list[str]) -> Path:
        slug = _slug(topic) or "feed"
        path = self._plugin_dir / f"{slug}_live_feed.py"
        endpoint = endpoints[0] if endpoints else ""
        summary = str(docs.get("summary", "")).replace('"""', "'''")[:1000]
        source = f'''"""Auto-generated live feed scaffold for {topic}."""

try:
    import requests
except Exception:  # pragma: no cover
    requests = None

LAST_PAYLOAD = {{}}
PRIMARY_ENDPOINT = "{endpoint}"
DOC_SUMMARY = """{summary}"""

PLUGIN_TOOLS = [
    {{
        "name": "{slug}.poll",
        "description": "Poll live feed endpoint and return deltas only.",
        "args": {{"url": "optional override endpoint"}},
        "fn": "poll",
    }},
]


def poll(url: str = "") -> dict:
    global LAST_PAYLOAD
    if requests is None:
        return {{"status": "error", "reason": "requests_not_available"}}
    target = (url or PRIMARY_ENDPOINT).strip()
    if not target:
        return {{"status": "error", "reason": "missing_endpoint"}}
    try:
        resp = requests.get(target, timeout=15)
        data = resp.text[:4000]
        changed = data != LAST_PAYLOAD.get("raw", "")
        LAST_PAYLOAD["raw"] = data
        return {{"status": "ok", "changed": changed, "preview": data[:400]}}
    except Exception as exc:
        return {{"status": "error", "reason": str(exc), "url": target}}
'''
        return self._write_plugin_file(path, source)

    def _write_recovery_plugin(self, *, step_key: str, vision: dict[str, Any]) -> Path:
        slug = _slug(step_key) or "step"
        path = self._plugin_dir / f"recovery_{slug}.py"
        compact_vision = json.dumps(vision, ensure_ascii=False)[:1200].replace('"""', "'''")
        source = f'''"""Auto-generated recovery scaffold for repeated failure: {step_key}."""

VISION_HINT = """{compact_vision}"""

PLUGIN_TOOLS = [
    {{
        "name": "recovery.{slug}.precheck",
        "description": "Run precheck before retrying failed step.",
        "args": {{"context": "optional context"}},
        "fn": "precheck",
    }},
    {{
        "name": "recovery.{slug}.fallback",
        "description": "Run fallback strategy for failed step.",
        "args": {{"context": "optional context"}},
        "fn": "fallback",
    }},
]


def precheck(context: str = "") -> dict:
    return {{"status": "ok", "step": "{step_key}", "phase": "precheck", "context": context}}


def fallback(context: str = "") -> dict:
    return {{"status": "ok", "step": "{step_key}", "phase": "fallback", "context": context}}
'''
        return self._write_plugin_file(path, source)

    def _write_mode_plugin(self, *, context_label: str) -> Path:
        slug = _slug(context_label) or "context"
        path = self._plugin_dir / f"mode_{slug}.py"
        source = f'''"""Auto-generated context mode scaffold for: {context_label}."""

MODE = {{
    "label": "{context_label}",
    "mute_notifications": False,
    "short_responses": True,
    "autonomy_depth": "medium",
}}

PLUGIN_TOOLS = [
    {{
        "name": "mode.{slug}.apply",
        "description": "Apply context-aware assistant behavior mode.",
        "args": {{}},
        "fn": "apply_mode",
    }},
    {{
        "name": "mode.{slug}.status",
        "description": "Return current mode settings.",
        "args": {{}},
        "fn": "status",
    }},
]


def apply_mode() -> dict:
    return {{"status": "ok", "applied": True, "mode": MODE}}


def status() -> dict:
    return {{"status": "ok", "mode": MODE}}
'''
        return self._write_plugin_file(path, source)

    @staticmethod
    def _write_plugin_file(path: Path, source: str) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
        return path

    def _scan_lan_devices(self) -> dict[str, Any]:
        devices: list[dict[str, str]] = []
        try:
            out = subprocess.check_output(["arp", "-a"], text=True, stderr=subprocess.STDOUT, timeout=10)
            for line in out.splitlines():
                ip_match = re.search(r"\((\d+\.\d+\.\d+\.\d+)\)", line)
                mac_match = re.search(r"(([0-9a-f]{2}[:-]){5}[0-9a-f]{2})", line.lower())
                if not ip_match or not mac_match:
                    continue
                ip = ip_match.group(1)
                mac = mac_match.group(1).replace("-", ":")
                devices.append(
                    {
                        "ip": ip,
                        "mac": mac,
                        "vendor_hint": _vendor_hint(mac),
                    }
                )
        except Exception as exc:
            return {"status": "error", "reason": str(exc), "devices": []}
        return {"status": "ok", "devices": devices}

    def _write_device_plugin_stubs(self, devices: list[dict[str, str]]) -> list[str]:
        plugins_dir = self._plugin_dir
        plugins_dir.mkdir(parents=True, exist_ok=True)
        created: list[str] = []
        has_bulb = any("philips" in (d.get("vendor_hint", "").lower()) or "tuya" in (d.get("vendor_hint", "").lower()) for d in devices)
        has_ac = any("daikin" in (d.get("vendor_hint", "").lower()) or "lg" in (d.get("vendor_hint", "").lower()) for d in devices)
        if has_bulb:
            p = plugins_dir / "bulb_control.py"
            if not p.exists():
                p.write_text(_stub_plugin("bulb_control", "bulb.toggle", "Toggle a smart bulb by id"), encoding="utf-8")
                created.append(str(p))
        if has_ac:
            p = plugins_dir / "ac_control.py"
            if not p.exists():
                p.write_text(_stub_plugin("ac_control", "ac.set_temp", "Set AC temperature by zone"), encoding="utf-8")
                created.append(str(p))
        return created

    def _persist_jobs(self) -> None:
        payload = [
            {
                "id": j.id,
                "kind": j.kind,
                "payload": j.payload,
                "created_at": j.created_at,
                "status": j.status,
                "attempts": j.attempts,
                "last_error": j.last_error,
            }
            for j in self._jobs
        ]
        self._queue_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _load_jobs(self) -> None:
        try:
            if not self._queue_path.exists():
                return
            rows = json.loads(self._queue_path.read_text(encoding="utf-8"))
            for row in rows:
                self._jobs.append(
                    BatchJob(
                        id=str(row.get("id", "")),
                        kind=str(row.get("kind", "")),
                        payload=dict(row.get("payload", {}) or {}),
                        created_at=float(row.get("created_at", time.time())),
                        status=str(row.get("status", "queued")),
                        attempts=int(row.get("attempts", 0)),
                        last_error=str(row.get("last_error", "")),
                    )
                )
            if any(j.status == "queued" for j in self._jobs):
                with self._lock:
                    self._ensure_worker_locked()
        except Exception:
            self._jobs = []


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", (text or "").lower()).strip("_")


def _vendor_hint(mac: str) -> str:
    oui = mac.lower().replace("-", ":")[:8]
    table = {
        "00:17:88": "Philips",
        "a4:cf:12": "Tuya",
        "f4:f5:d8": "LG",
        "00:1c:42": "Daikin",
    }
    return table.get(oui, "Unknown")


def _stub_plugin(plugin_name: str, tool_name: str, description: str) -> str:
    return f'''"""Auto-generated smart-home plugin stub: {plugin_name}."""

PLUGIN_TOOLS = [
    {{
        "name": "{tool_name}",
        "description": "{description}",
        "args": {{"device_id": "Target device id", "value": "Optional value"}},
        "fn": "run",
    }},
]


def run(device_id: str, value: str = "") -> dict:
    return {{"status": "stub", "plugin": "{plugin_name}", "device_id": device_id, "value": value}}
'''


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
