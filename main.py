"""NOVA entry point."""

from __future__ import annotations

import json
import logging
import queue
import signal
import time
from pathlib import Path
import re
import threading
from collections import deque
from typing import Any, Generator
from datetime import date

from pydantic import BaseModel, Field

from config.constants import DEFAULT_MEMORY_TOP_K, DEFAULT_SYSTEM_PROMPT
from config.settings import SettingsError, settings
from core.context.environment import snapshot_environment
from core.emotion.engine import EmotionEngine
from core.health import HealthMonitor
from core.llm.fallback import NetworkState
from core.llm.engine import LLMEngine
from core.memory.context_trimmer import ContextTrimmer
from core.memory.local_store import LocalMemoryStore
from core.memory.mem0_client import Mem0Client
from core.memory.memory_router import MemoryRouter
from core.plugin_loader import load_plugins
from core.session import SessionManager
from core.think.reasoning import build_system_prompt, clarifying_question, needs_clarification
from core.tools.dispatcher import Dispatcher
from control.adb.adb_client import ADBClient
from control.adb.qr_pairing import QRPairing
from control.adb.tailscale import ensure_tailscale_connected, tailscale_ip_v4, tailscale_status
from control.adb.watcher import PhoneWatcher
from control.browser import Browser
from interfaces.cli import run_cli
from mcp.master_api import MasterAPI
from mcp.master_mcp import BUILTIN_SERVICES, MasterMCP
from rag.doc_store import DocumentStore
from safety.guardrails import guardrails
from tasks.scheduler import TaskScheduler
from tasks.goals import GoalRunner
from utils.exporter import export_json, export_markdown
from utils.goals import format_goal_list
from utils.health import format_health_table, summarize_health
from utils.logger import setup_logger
from utils.notifier import build_goal_status_message, notify_background_event, send_telegram_text
from utils.token_estimator import estimate_tokens, estimate_tokens_from_messages
from utils.usage_tracker import UsageTracker
from vision.watcher import ScreenWatcher
from vision.omniparser_server import OmniParserServer
from web.crawler import crawl
from web.scraper import scrape_text
from web.search import search
import control.win32_api as win32_api

logger = logging.getLogger(__name__)


class WebSearchArgs(BaseModel):
    query: str
    max_results: int = Field(default=5, ge=1, le=20)


class WebScrapeArgs(BaseModel):
    url: str


class WebCrawlArgs(BaseModel):
    seed_url: str
    max_pages: int = Field(default=5, ge=1, le=50)


class DocIngestArgs(BaseModel):
    filepath: str


class DocQueryArgs(BaseModel):
    question: str
    filename: str | None = None
    top_k: int = Field(default=5, ge=1, le=20)


class SessionSwitchArgs(BaseModel):
    name: str


class FileReadArgs(BaseModel):
    path: str


class FileWriteArgs(BaseModel):
    path: str
    content: str


class FileMoveArgs(BaseModel):
    src: str
    dst: str


class FileDeleteArgs(BaseModel):
    path: str


class FileSearchArgs(BaseModel):
    root: str
    name_pattern: str = "*"
    content_query: str | None = None


class ClipboardSetArgs(BaseModel):
    text: str


class DiskInfoArgs(BaseModel):
    paths: list[str] | None = None


class WindowTitleArgs(BaseModel):
    title: str


class WindowResizeArgs(BaseModel):
    title: str
    width: int
    height: int


class RegistryReadArgs(BaseModel):
    path: str
    name: str


class RegistryWriteArgs(BaseModel):
    path: str
    name: str
    value: str
    value_type: str = "REG_SZ"


class NotificationArgs(BaseModel):
    title: str
    message: str


class ProcessKillArgs(BaseModel):
    name_or_pid: str


class ProcessLaunchArgs(BaseModel):
    command: str


class BrowserOpenArgs(BaseModel):
    url: str


class BrowserClickArgs(BaseModel):
    selector: str


class BrowserFillArgs(BaseModel):
    selector: str
    value: str


class BrowserWaitTextArgs(BaseModel):
    text: str
    timeout_ms: int = Field(default=10_000, ge=100, le=120_000)


class BrowserScreenshotArgs(BaseModel):
    path: str = "assets/browser_screen.png"


class MouseClickArgs(BaseModel):
    x: int
    y: int


class MouseClickElementArgs(BaseModel):
    name: str


class KeyboardTypeArgs(BaseModel):
    text: str


class KeyboardHotkeyArgs(BaseModel):
    keys: list[str] = Field(default_factory=list)


class MouseScrollArgs(BaseModel):
    clicks: int


class MouseDragArgs(BaseModel):
    start_x: int
    start_y: int
    end_x: int
    end_y: int
    duration: float = Field(default=0.25, ge=0.0, le=10.0)


class ADBConnectArgs(BaseModel):
    host: str
    port: int = Field(default=5555, ge=1, le=65535)


class ADBTapArgs(BaseModel):
    x: int
    y: int


class ADBSwipeArgs(BaseModel):
    x1: int
    y1: int
    x2: int
    y2: int
    duration_ms: int = Field(default=250, ge=1, le=20_000)


class ADBTextArgs(BaseModel):
    text: str


class ADBLaunchArgs(BaseModel):
    package_name: str


class ADBKeyEventArgs(BaseModel):
    key_code: str


class ADBPullArgs(BaseModel):
    remote_path: str
    local_path: str


class ADBPushArgs(BaseModel):
    local_path: str
    remote_path: str


class ADBSmsArgs(BaseModel):
    phone_number: str
    body: str


class QRGenerateArgs(BaseModel):
    out_path: str = "assets/adb_qr.png"
    prefer_remote: bool = False


class QRTerminalArgs(BaseModel):
    prefer_remote: bool = False


class EmptyArgs(BaseModel):
    pass


class TaskScheduleArgs(BaseModel):
    schedule_text: str
    prompt: str
    job_id: str | None = None


class TaskCancelArgs(BaseModel):
    job_id: str


class GoalStepArgs(BaseModel):
    tool: str
    args: dict = Field(default_factory=dict)


class GoalRunArgs(BaseModel):
    goal: str
    steps: list[GoalStepArgs]
    max_steps: int = Field(default=20, ge=1, le=50)
    dry_run: bool = False


class GoalPlanArgs(BaseModel):
    goal: str
    max_steps: int = Field(default=10, ge=1, le=30)


class GoalAddArgs(BaseModel):
    goal: str
    max_steps: int = Field(default=20, ge=1, le=50)


class GoalCancelArgs(BaseModel):
    goal_id: str


class GoalResumeArgs(BaseModel):
    goal_id: str


class GoalQueryArgs(BaseModel):
    goal_id: str


class MCPRegisterKeyArgs(BaseModel):
    service: str = ""
    api_key: str


class MCPConnectArgs(BaseModel):
    service: str
    endpoint: str | None = None
    api_key: str | None = None
    headers: dict[str, str] | None = None
    timeout_seconds: int = Field(default=20, ge=1, le=120)
    discover: bool = True


class MCPListToolsArgs(BaseModel):
    service: str | None = None


class MCPCallToolArgs(BaseModel):
    service: str
    tool_name: str
    args: dict = Field(default_factory=dict)


class ExportSessionArgs(BaseModel):
    format: str = "md"


class SetMuteArgs(BaseModel):
    muted: bool


class JarvisApp:
    def __init__(self):
        settings.validate_startup(phase="minimal")

        self.dispatcher = Dispatcher()
        self.scheduler = TaskScheduler()
        self.master_api = MasterAPI()
        self.master_mcp = MasterMCP()
        self.session = SessionManager(default_name=settings.DEFAULT_SESSION)
        self._muted = False
        self.trimmer = ContextTrimmer(max_raw_turns=10)
        self.health = HealthMonitor(on_change=self._handle_health_event)
        self.emotion = EmotionEngine()
        self.usage = UsageTracker()
        self._usage_alerted_day = None
        self._hard_cap_hit = False

        # Tracking for daily resets
        self._hard_cap_hit_date: date | None = None

        # Summary cache
        self._summary_cache: dict[int, str] = {}
        self._summary_cache_lock = threading.Lock()
        self._last_snippet_hash: int | None = None

        self._tts_queue: queue.Queue = queue.Queue()
        self._tts_thread = threading.Thread(target=self._tts_worker, daemon=True)
        self._tts_thread.start()

        self._summarize_semaphore = threading.Semaphore(1)

        self._event_lock = threading.Lock()
        self._events = deque(maxlen=100)

        # Guard Mem0Client init — skip if key is missing to avoid crash at startup
        _mem0_key = settings.MEM0_API_KEY
        _mem0_client = Mem0Client(api_key=_mem0_key) if _mem0_key else None

        self.memory = MemoryRouter(
            mem0=_mem0_client,
            local=LocalMemoryStore(),
        )
        self.docs = DocumentStore()
        self._browser: Browser | None = None
        self._mouse_keyboard: Any | None = None
        self._omniparser_client: Any | None = None
        self.adb = ADBClient()
        self.qr = QRPairing(adb_port=settings.ADB_PORT)
        self.omniparser = OmniParserServer(
            url=settings.OMNIPARSER_SERVER_URL,
            repo_dir=settings.OMNIPARSER_REPO_DIR,
        )
        self._goals: list[dict] = []
        self._goal_lock = threading.Lock()
        self._autonomy_stop = threading.Event()
        self._autonomy_thread: threading.Thread | None = None
        self._emergency_hotkey_listener: Any | None = None
        self.screen_watcher = ScreenWatcher(
            interval_seconds=settings.PROACTIVE_WATCHER_INTERVAL,
            cooldown_seconds=settings.PROACTIVE_WATCHER_COOLDOWN,
            on_alert=self._handle_proactive_alert,
            omniparser_url=settings.OMNIPARSER_SERVER_URL,
        )
        self.phone_watcher = PhoneWatcher(adb=self.adb, on_alert=self._handle_proactive_alert)
        self.engine = LLMEngine(
            openai_base_url=settings.OPENAI_BASE_URL or "http://localhost:11434",
            openai_keys=settings.OPENAI_API_KEYS,
            ollama_base_url=settings.OLLAMA_BASE_URL,
            ollama_model=settings.OLLAMA_MODEL,
        )
        self.base_system_prompt = DEFAULT_SYSTEM_PROMPT
        self._register_builtin_tools()
        self.goal_runner = GoalRunner(self.dispatcher)
        load_plugins(self.dispatcher)
        self._start_health_monitoring()
        self._start_watchers_if_enabled()
        self._start_autonomy_loop()
        self._start_emergency_hotkey()
        self.scheduler.start()

    def last_provider_label(self) -> str:
        return self.engine.last_provider

    @property
    def emotion_state(self) -> str:
        return self.emotion.state

    def switch_session(self, name: str):
        return self.session.switch(name)

    def reset_context(self) -> None:
        """Clear current session history and the associated trimmer summary.

        Also auto-exports as a backup before clearing.
        """
        session_id = self.session.current.session_id
        try:
            self.export_session("md")
        except Exception:
            pass
        self.session.reset_context()
        self.trimmer.summaries.pop(session_id, None)

    def list_goals(self) -> list[dict]:
        return self._list_goals()

    def goal_status_text(self) -> str:
        return format_goal_list(self._list_goals())

    def add_goal(self, goal: str, max_steps: int = 20) -> dict:
        return self._add_goal(goal, max_steps=max_steps)

    def resume_goal(self, goal_id: str) -> dict:
        return self._resume_goal(goal_id)

    def cancel_goal(self, goal_id: str) -> dict:
        return self._cancel_goal(goal_id)

    def query_goal(self, goal_id: str) -> dict:
        for item in self._list_goals():
            if str(item.get("id")) == str(goal_id):
                return item
        return {"goal_id": goal_id, "status": "not_found"}

    def is_muted(self) -> bool:
        return bool(self._muted)

    def set_muted(self, muted: bool) -> bool:
        self._muted = bool(muted)
        return self._muted

    def toggle_mute(self) -> bool:
        self._muted = not self._muted
        return self._muted

    def record_event(self, kind: str, message: str) -> dict:
        entry = {
            "kind": kind,
            "message": message,
            "timestamp": time.time(),
        }
        with self._event_lock:
            self._events.appendleft(entry)
        return entry

    def recent_events(self, limit: int = 20) -> list[dict]:
        with self._event_lock:
            return [dict(item) for item in list(self._events)[: max(1, int(limit))]]

    def export_session(self, fmt: str = "md") -> str:
        session = self.session.current
        timestamp = int(time.time())
        safe_name = re.sub(r"[^a-zA-Z0-9_-]+", "_", session.name).strip("_") or "session"
        # Ensure exports/ directory exists before writing
        Path("exports").mkdir(parents=True, exist_ok=True)
        if fmt.lower() == "json":
            path = f"exports/{safe_name}_{timestamp}.json"
            return export_json(session.history, path)
        path = f"exports/{safe_name}_{timestamp}.md"
        return export_markdown(session.history, path)

    def status_text(self) -> str:
        health_items = self.health.status_table()
        # NOVA-FIX-2: Guard pool access — pool may be None when no cloud keys set
        active_cloud_keys = self.engine.pool.active_count() if self.engine.pool is not None else 0
        return json.dumps(
            {
                "session": self.session.current.name,
                "session_id": self.session.current.session_id,
                "active_cloud_keys": active_cloud_keys,
                "memory_mode": "online" if self.memory.online else "offline",
                "provider_last": self.engine.last_provider,
                "emotion": self.emotion.state,
                "usage_today": self.usage.today_summary(session_id=self.session.current.session_id),
                "usage_week": self.usage.weekly_summary(session_id=self.session.current.session_id),
                "tailscale_ip": tailscale_ip_v4(),
                "tailscale_status": tailscale_status(),
                "mcp_connected_services": self.master_mcp.list_services(),
                "mcp_registered_keys": self.master_api.list_services(),
                "muted": self._muted,
                "autonomy_notify_telegram": settings.AUTONOMY_NOTIFY_TELEGRAM,
                "autonomy_notify_tts": settings.AUTONOMY_NOTIFY_TTS,
                "health_summary": summarize_health(health_items),
                "health": health_items,
                "health_table": format_health_table(health_items),
            },
            indent=2,
        )

    def _get_browser(self) -> Browser:
        if self._browser is None:
            self._browser = Browser(headless=True)
        return self._browser

    def _get_mouse_keyboard(self):
        if self._mouse_keyboard is None:
            from control.mouse_keyboard import MouseKeyboard
            self._mouse_keyboard = MouseKeyboard()
        return self._mouse_keyboard

    def _get_omniparser_client(self):
        current_token = self.omniparser.auth_token if hasattr(self, 'omniparser') else None
        if self._omniparser_client is None:
            from vision.omniparser import OmniParserClient
            self._omniparser_client = OmniParserClient(
                settings.OMNIPARSER_SERVER_URL,
                auth_token=current_token
            )
        else:
            self._omniparser_client.auth_token = current_token
        return self._omniparser_client

    def _current_ui_elements(self) -> list[dict[str, Any]]:
        from vision.capture import capture_active_window_png
        image_bytes = capture_active_window_png()
        return self._get_omniparser_client().ui_elements(image_bytes)

    def _mouse_click(self, x: int, y: int) -> dict:
        self._get_mouse_keyboard().click(x, y)
        return {"clicked": True, "x": x, "y": y}

    def _mouse_click_element(self, name: str) -> dict:
        elements = self._current_ui_elements()
        controller = self._get_mouse_keyboard()
        result = controller.click_element_result(name, elements)
        result["available_elements"] = len(elements)
        return result

    def _keyboard_type_text(self, text: str) -> dict:
        self._get_mouse_keyboard().type_text(text)
        return {"typed": True, "length": len(text)}

    def _keyboard_hotkey(self, keys: list[str]) -> dict:
        cleaned = [key.strip() for key in keys if key.strip()]
        if not cleaned:
            return {"pressed": False, "reason": "no_keys"}
        self._get_mouse_keyboard().hotkey(*cleaned)
        return {"pressed": True, "keys": cleaned}

    def _mouse_scroll(self, clicks: int) -> dict:
        self._get_mouse_keyboard().scroll(clicks)
        return {"scrolled": True, "clicks": clicks}

    def _mouse_drag(
        self,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        duration: float = 0.25,
    ) -> dict:
        self._get_mouse_keyboard().drag(start_x, start_y, end_x, end_y, duration=duration)
        return {
            "dragged": True,
            "from": {"x": start_x, "y": start_y},
            "to": {"x": end_x, "y": end_y},
            "duration": duration,
        }

    def _browser_open(self, url: str) -> str:
        self._get_browser().open(url)
        return f"opened {url}"

    def _browser_click(self, selector: str) -> str:
        self._get_browser().click(selector)
        return f"clicked {selector}"

    def _browser_fill(self, selector: str, value: str) -> str:
        self._get_browser().fill(selector, value)
        return f"filled {selector}"

    def _browser_extract_text(self) -> str:
        return self._get_browser().extract_text()

    def _browser_get_links(self) -> list[str]:
        return self._get_browser().get_links()

    def _browser_wait_for_text(self, text: str, timeout_ms: int = 10_000) -> bool:
        return self._get_browser().wait_for_text(text, timeout_ms=timeout_ms)

    def _browser_screenshot(self, path: str = "assets/browser_screen.png") -> str:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        self._get_browser().screenshot(path=str(target))
        return str(target)

    def _browser_close(self) -> str:
        if self._browser is None:
            return "browser not running"
        self._browser.close()
        self._browser = None
        return "browser closed"

    def _schedule_prompt(self, schedule_text: str, prompt: str, job_id: str | None = None) -> dict:
        job_id = job_id or f"job_{int(time.time())}"

        def _run() -> None:
            response = "".join(self.ask_stream(prompt, allow_tools=False))
            print(f"\n[scheduled:{job_id}] {response}")

        cron = self.scheduler.add_from_text(_run, schedule_text, job_id=job_id)
        return {"job_id": job_id, "schedule": cron}

    def _list_jobs(self) -> list[dict]:
        return self.scheduler.list_jobs_detailed()

    def _cancel_job(self, job_id: str) -> dict:
        ok = self.scheduler.remove_job(job_id)
        return {"job_id": job_id, "status": "cancelled" if ok else "not_found"}

    def _run_goal(self, goal: str, steps: list[GoalStepArgs], max_steps: int = 20, dry_run: bool = False) -> dict:
        step_dicts = [{"tool": step.tool, "args": step.args} for step in steps]
        result = self.goal_runner.run(step_dicts, max_steps=max_steps, dry_run=dry_run)
        return {
            "goal": goal,
            "status": result.status,
            "reason": result.reason,
            "results": result.results,
            "next_index": result.next_index,
        }

    def _plan_goal(self, goal: str, max_steps: int = 10) -> dict:
        planner_prompt = (
            "You are a planning assistant. Break the user's goal into a short sequence of tool calls.\n"
            "Return ONLY valid JSON. Prefer this format:\n"
            '[{"tool": "<tool_name>", "args": {...}}, ...]\n'
            "No prose, no markdown. Keep it concise."
        )
        system_prompt = build_system_prompt(
            planner_prompt,
            dispatcher=self.dispatcher,
            emotion=self.emotion.state,
        )
        raw = self.engine.ask(prompt=f"Goal: {goal}", system=system_prompt, history=[])

        def _extract_steps(text: str) -> list[dict]:
            text = text.strip()
            if not text:
                return []
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                match = re.search(r"\[.*\]", text, flags=re.DOTALL)
                if not match:
                    return []
                try:
                    data = json.loads(match.group(0))
                except json.JSONDecodeError:
                    return []
            if isinstance(data, dict) and "steps" in data:
                data = data["steps"]
            if not isinstance(data, list):
                return []
            steps = []
            for item in data:
                if not isinstance(item, dict):
                    continue
                tool = item.get("tool") or item.get("name")
                args = item.get("args") or {}
                if tool:
                    steps.append({"tool": tool, "args": args})
            return steps

        steps = _extract_steps(raw)
        if not steps:
            return {"goal": goal, "status": "failed", "reason": "no_steps_parsed", "raw": raw}
        if len(steps) > max_steps:
            steps = steps[:max_steps]
        return {"goal": goal, "status": "ok", "steps": steps, "raw": raw}

    def _add_goal(self, goal: str, max_steps: int = 20) -> dict:
        plan = self._plan_goal(goal, max_steps=min(max_steps, 30))
        if plan.get("status") != "ok":
            return plan
        goal_id = f"goal_{int(time.time())}"
        record = {
            "id": goal_id,
            "goal": goal,
            "steps": plan["steps"],
            "status": "pending",
            "created_at": time.time(),
            "max_steps": max_steps,
            "cursor": 0,
        }
        with self._goal_lock:
            self._goals.append(record)
        return record

    def _list_goals(self) -> list[dict]:
        with self._goal_lock:
            return [dict(item) for item in self._goals]

    def _cancel_goal(self, goal_id: str) -> dict:
        with self._goal_lock:
            for item in self._goals:
                if item.get("id") == goal_id:
                    if item.get("status") == "pending":
                        item["status"] = "cancelled"
                        return {"goal_id": goal_id, "status": "cancelled"}
                    return {"goal_id": goal_id, "status": "not_pending"}
        return {"goal_id": goal_id, "status": "not_found"}

    def _resume_goal(self, goal_id: str) -> dict:
        with self._goal_lock:
            for item in self._goals:
                if item.get("id") == goal_id:
                    if item.get("status") in {"paused", "failed"}:
                        item["status"] = "pending"
                        return {"goal_id": goal_id, "status": "pending"}
                    if item.get("status") == "completed":
                        return {"goal_id": goal_id, "status": "already_completed"}
                    return {"goal_id": goal_id, "status": item.get("status")}
        return {"goal_id": goal_id, "status": "not_found"}

    def _register_mcp_api_key(self, service: str = "", api_key: str = "") -> dict:
        if not api_key.strip():
            return {"status": "error", "reason": "api_key_required"}
        resolved = self.master_api.register(service, api_key)
        return {
            "status": "ok",
            "service": resolved,
            "api_key": self.master_api.masked(resolved),
        }

    def _connect_mcp(
        self,
        service: str,
        endpoint: str | None = None,
        api_key: str | None = None,
        headers: dict[str, str] | None = None,
        timeout_seconds: int = 20,
        discover: bool = True,
    ) -> dict:
        svc = service.strip().lower()
        if not svc:
            return {"status": "error", "reason": "service_required"}

        key = (api_key or "").strip() or (self.master_api.get(svc) or "")
        if endpoint:
            merged_headers = dict(headers or {})
            if key and "Authorization" not in merged_headers:
                merged_headers["Authorization"] = f"Bearer {key}"
            self.master_mcp.connect_http(
                service=svc,
                endpoint=endpoint,
                headers=merged_headers,
                timeout_seconds=timeout_seconds,
                discover=discover,
            )
        elif svc in BUILTIN_SERVICES:
            if not key:
                return {
                    "status": "error",
                    "reason": f"api_key_required_for_builtin:{svc}",
                }
            self.master_mcp.connect_builtin(svc, key)
        else:
            return {
                "status": "error",
                "reason": f"unsupported_service_or_missing_endpoint:{svc}",
            }

        return {
            "status": "ok",
            "service": svc,
            "connected": self.master_mcp.is_connected(svc),
            "tools": self.master_mcp.list_tools(service=svc),
        }

    def _list_mcp_services(self) -> dict:
        return {
            "connected": self.master_mcp.list_services(),
            "registered_keys": self.master_api.list_services(),
        }

    def _list_mcp_tools(self, service: str | None = None) -> list[dict]:
        return self.master_mcp.list_tools(service=service)

    def _call_mcp_tool(self, service: str, tool_name: str, args: dict | None = None) -> dict:
        payload = args or {}
        result = self.master_mcp.call_tool(service, tool_name, **payload)
        if isinstance(result, dict):
            return result
        return {"result": result}

    def _safety_emergency_stop(self) -> dict:
        guardrails.emergency_stop()
        return {"status": "ok", "emergency_stop": True}

    def _safety_clear_stop(self) -> dict:
        guardrails.clear_emergency_stop()
        return {"status": "ok", "emergency_stop": False}

    def _safety_status(self) -> dict:
        return {"emergency_stop": guardrails.is_emergency_stopped()}

    def _session_export_tool(self, format: str = "md") -> dict:
        fmt = format.lower().strip()
        if fmt not in {"md", "markdown", "json"}:
            return {"status": "error", "reason": "format_must_be_md_or_json"}
        normalized = "md" if fmt in {"md", "markdown"} else "json"
        path = self.export_session(normalized)
        return {"status": "ok", "path": path, "format": normalized}

    def _set_mute_tool(self, muted: bool) -> dict:
        state = self.set_muted(muted)
        return {"status": "ok", "muted": state}

    def _mute_status_tool(self) -> dict:
        return {"muted": self.is_muted()}

    def _start_health_monitoring(self) -> None:
        self.health.register_subsystem("jarvis", lambda: True)
        self.health.register_subsystem("network", lambda: NetworkState.is_online())
        self.health.register_subsystem("memory_router", lambda: self.memory is not None)
        self.health.register_subsystem(
            "tailscale",
            lambda: tailscale_status() not in {"down"},
            restart_fn=ensure_tailscale_connected,
        )
        self.health.register_subsystem(
            "omniparser",
            check_fn=self.omniparser.is_running,
            restart_fn=self.omniparser.restart,
        )
        if settings.PROACTIVE_WATCHER_ENABLED:
            self.health.register_subsystem(
                "screen_watcher",
                check_fn=self.screen_watcher.is_running,
                restart_fn=self.screen_watcher.restart,
            )
        if settings.PHONE_WATCHER_ENABLED:
            self.health.register_subsystem(
                "phone_watcher",
                check_fn=self.phone_watcher.is_running,
                restart_fn=self.phone_watcher.restart,
            )
        if settings.AUTONOMY_ENABLED:
            self.health.register_subsystem(
                "autonomy_loop",
                check_fn=self._autonomy_is_running,
                restart_fn=self._start_autonomy_loop,
            )
        try:
            self.omniparser.ensure_running()
        except Exception:
            pass
        self.health.start(interval_seconds=60)

    def _start_watchers_if_enabled(self) -> None:
        if settings.PROACTIVE_WATCHER_ENABLED:
            try:
                self.screen_watcher.start()
            except Exception:
                pass
        if settings.PHONE_WATCHER_ENABLED:
            try:
                self.phone_watcher.start()
            except Exception:
                pass

    def _autonomy_is_running(self) -> bool:
        return self._autonomy_thread is not None and self._autonomy_thread.is_alive()

    def _start_autonomy_loop(self) -> None:
        if not settings.AUTONOMY_ENABLED or self._autonomy_is_running():
            return
        self._autonomy_stop.clear()
        self._autonomy_thread = threading.Thread(target=self._autonomy_loop, daemon=True)
        self._autonomy_thread.start()

    def _start_emergency_hotkey(self) -> None:
        try:
            from pynput import keyboard

            if not settings.VOICE_BARGEIN_ENABLED:
                self._emergency_hotkey_listener = None
                return

            raw_hotkey = settings.VOICE_BARGEIN_HOTKEY.lower()
            formatted = []
            for p in raw_hotkey.split("+"):
                if len(p) > 1:
                    formatted.append(f"<{p.strip()}>")
                else:
                    formatted.append(p.strip())
            hotkey_str = "+".join(formatted)

            self._emergency_hotkey_listener = keyboard.GlobalHotKeys(
                {hotkey_str: guardrails.emergency_stop}
            )
            self._emergency_hotkey_listener.start()
        except Exception as exc:
            logger.warning("Emergency hotkey setup failed — hotkey will not be active: %s", exc)
            self._emergency_hotkey_listener = None

    def _stop_autonomy_loop(self) -> None:
        self._autonomy_stop.set()
        if self._autonomy_thread and self._autonomy_thread.is_alive():
            self._autonomy_thread.join(timeout=2)

    def _autonomy_loop(self) -> None:
        poll = max(2.0, float(settings.AUTONOMY_POLL_SECONDS))
        while not self._autonomy_stop.is_set():
            goal = None
            with self._goal_lock:
                for item in self._goals:
                    if item.get("status") == "pending":
                        item["status"] = "running"
                        item["started_at"] = time.time()
                        goal = dict(item)
                        break
            if not goal:
                self._autonomy_stop.wait(poll)
                continue

            steps = goal.get("steps") or []
            max_steps = int(goal.get("max_steps") or settings.AUTONOMY_MAX_STEPS)
            start_index = int(goal.get("cursor") or 0)
            result = self.goal_runner.run(steps, max_steps=max_steps, start_index=start_index)

            status = "completed" if result.status == "completed" else "paused"
            if result.status == "stopped" and "Cycle detected" in result.reason:
                status = "failed"
            if result.status == "stopped" and "max_steps" in result.reason:
                status = "paused"
            if result.status == "failed":
                status = "failed"

            with self._goal_lock:
                for item in self._goals:
                    if item.get("id") == goal.get("id"):
                        item["status"] = status
                        item["cursor"] = result.next_index
                        item["finished_at"] = time.time()
                        item["last_result"] = {
                            "status": result.status,
                            "reason": result.reason,
                            "results": result.results,
                            "next_index": result.next_index,
                        }
                        break

            message = build_goal_status_message(
                goal_id=str(goal.get("id")),
                goal=str(goal.get("goal")),
                status=status,
                reason=result.reason,
                next_index=result.next_index,
                total_steps=len(steps),
            )
            print(f"\n[autonomy] {message}")
            self.session.add_turn("assistant", message)
            self._notify_autonomy_event(message)

    def shutdown(self) -> None:
        self.health.stop()
        if settings.PROACTIVE_WATCHER_ENABLED:
            self.screen_watcher.stop()
        if settings.PHONE_WATCHER_ENABLED:
            self.phone_watcher.stop()
        self.scheduler.stop()
        self._stop_autonomy_loop()
        if self._emergency_hotkey_listener is not None:
            try:
                self._emergency_hotkey_listener.stop()
            except Exception:
                pass
        self._browser_close()
        try:
            self.omniparser.stop()
        except Exception:
            pass
        # Gracefully drain the TTS queue with sentinel
        self._tts_queue.put(None)

    def _handle_proactive_alert(self, message: str) -> None:
        self.record_event("proactive", message)
        if self._muted:
            return
        print(f"\n[proactive] {message}")
        self.session.add_turn("assistant", message)
        _ = notify_background_event(
            message,
            muted=self._muted,
            notify_telegram=self._notify_telegram,
            notify_tts=self._notify_tts,
        )

    def _handle_health_event(self, name: str, status: str, previous_status: str | None) -> None:
        message = f"Health update: {name} changed to {status}"
        if previous_status:
            message += f" (from {previous_status})"
        self.record_event("health", message)
        print(f"\n[health] {message}")
        if status in {"down", "restart_failed"}:
            _ = send_telegram_text(
                bot_token=settings.TELEGRAM_BOT_TOKEN,
                chat_id=settings.TELEGRAM_CHAT_ID,
                text=message,
            )

    def _notify_telegram(self, text: str) -> dict | None:
        if not settings.AUTONOMY_NOTIFY_TELEGRAM:
            return None
        result = send_telegram_text(
            bot_token=settings.TELEGRAM_BOT_TOKEN,
            chat_id=settings.TELEGRAM_CHAT_ID,
            text=text,
        )
        return result

    def _tts_worker(self) -> None:
        """TTS executed on a single dedicated background thread.

        NOVA-FIX-4: If voice.tts_offline import fails, we must still drain
        the queue so shutdown() does not hang forever on queue.join().
        The fallback loop discards all items but always calls task_done().
        """
        try:
            from voice.tts_offline import speak as speak_offline
        except Exception as exc:
            logger.warning("TTS offline module unavailable — voice output disabled: %s", exc)
            # Drain queue without speaking so shutdown sentinel is consumed
            while True:
                text = self._tts_queue.get()
                self._tts_queue.task_done()
                if text is None:
                    break
            return

        while True:
            text = self._tts_queue.get()
            if text is None:
                self._tts_queue.task_done()
                break
            try:
                speak_offline(text)
            except Exception as exc:
                logger.debug("TTS speak error: %s", exc)
            finally:
                self._tts_queue.task_done()

    def _notify_tts(self, text: str) -> bool:
        if not settings.AUTONOMY_NOTIFY_TTS:
            return False
        self._tts_queue.put(text)
        return True

    def _notify_autonomy_event(self, text: str) -> None:
        self.record_event("autonomy", text)
        if self._muted:
            return
        _ = self._notify_telegram(text)
        _ = self._notify_tts(text)

    def _register_builtin_tools(self) -> None:
        self.dispatcher.register("web.search", search, WebSearchArgs)
        self.dispatcher.register("web.scrape", scrape_text, WebScrapeArgs)
        self.dispatcher.register("web.crawl", crawl, WebCrawlArgs)
        self.dispatcher.register("doc.ingest", self.docs.ingest, DocIngestArgs)
        self.dispatcher.register("doc.query", self.docs.query, DocQueryArgs)
        self.dispatcher.register("doc.list", self.docs.list_docs, EmptyArgs)
        self.dispatcher.register("session.switch", lambda name: self.switch_session(name).name, SessionSwitchArgs)
        self.dispatcher.register("win32_api.read", win32_api.read_file, FileReadArgs)
        self.dispatcher.register("win32_api.write", win32_api.write_file, FileWriteArgs)
        self.dispatcher.register("win32_api.move", win32_api.move_file, FileMoveArgs)
        self.dispatcher.register("win32_api.delete", win32_api.delete_file, FileDeleteArgs)
        self.dispatcher.register("win32_api.list_processes", win32_api.list_processes, EmptyArgs)
        self.dispatcher.register("win32_api.search", win32_api.search_files, FileSearchArgs)
        self.dispatcher.register("win32_api.copy", win32_api.copy_file, FileMoveArgs)
        self.dispatcher.register("win32_api.kill_process", win32_api.kill_process, ProcessKillArgs)
        self.dispatcher.register("win32_api.launch_process", win32_api.launch_process, ProcessLaunchArgs)
        self.dispatcher.register("win32_api.get_clipboard", win32_api.get_clipboard, EmptyArgs)
        self.dispatcher.register("win32_api.set_clipboard", win32_api.set_clipboard, ClipboardSetArgs)
        self.dispatcher.register("win32_api.disk_info", win32_api.disk_info, DiskInfoArgs)
        self.dispatcher.register("win32_api.list_windows", win32_api.list_windows, EmptyArgs)
        self.dispatcher.register("win32_api.focus_window", win32_api.focus_window, WindowTitleArgs)
        self.dispatcher.register("win32_api.close_window", win32_api.close_window, WindowTitleArgs)
        self.dispatcher.register("win32_api.resize_window", win32_api.resize_window, WindowResizeArgs)
        self.dispatcher.register("win32_api.registry_read", win32_api.registry_read, RegistryReadArgs)
        self.dispatcher.register("win32_api.registry_write", win32_api.registry_write, RegistryWriteArgs)
        self.dispatcher.register("win32_api.send_notification", win32_api.send_notification, NotificationArgs)
        self.dispatcher.register("mouse.click", self._mouse_click, MouseClickArgs)
        self.dispatcher.register("mouse.click_element", self._mouse_click_element, MouseClickElementArgs)
        self.dispatcher.register("keyboard.type_text", self._keyboard_type_text, KeyboardTypeArgs)
        self.dispatcher.register("keyboard.hotkey", self._keyboard_hotkey, KeyboardHotkeyArgs)
        self.dispatcher.register("mouse.scroll", self._mouse_scroll, MouseScrollArgs)
        self.dispatcher.register("mouse.drag", self._mouse_drag, MouseDragArgs)
        self.dispatcher.register("browser.open", self._browser_open, BrowserOpenArgs)
        self.dispatcher.register("browser.click", self._browser_click, BrowserClickArgs)
        self.dispatcher.register("browser.fill", self._browser_fill, BrowserFillArgs)
        self.dispatcher.register("browser.extract_text", self._browser_extract_text, EmptyArgs)
        self.dispatcher.register("browser.get_links", self._browser_get_links, EmptyArgs)
        self.dispatcher.register("browser.wait_for_text", self._browser_wait_for_text, BrowserWaitTextArgs)
        self.dispatcher.register("browser.screenshot", self._browser_screenshot, BrowserScreenshotArgs)
        self.dispatcher.register("browser.close", self._browser_close, EmptyArgs)
        self.dispatcher.register("adb.connect", self.adb.connect, ADBConnectArgs)
        self.dispatcher.register("adb.devices", self.adb.devices, EmptyArgs)
        self.dispatcher.register("adb.tap", self.adb.tap, ADBTapArgs)
        self.dispatcher.register("adb.swipe", self.adb.swipe, ADBSwipeArgs)
        self.dispatcher.register("adb.type_text", self.adb.type_text, ADBTextArgs)
        self.dispatcher.register("adb.launch_app", self.adb.launch_app, ADBLaunchArgs)
        self.dispatcher.register("adb.keyevent", self.adb.keyevent, ADBKeyEventArgs)
        self.dispatcher.register("adb.pull", self.adb.pull, ADBPullArgs)
        self.dispatcher.register("adb.push", self.adb.push, ADBPushArgs)
        self.dispatcher.register("adb.send_sms", self.adb.send_sms, ADBSmsArgs)
        self.dispatcher.register("adb.notifications_dump", self.adb.notifications_dump, EmptyArgs)
        self.dispatcher.register("adb.sms_dump", self.adb.sms_dump, EmptyArgs)
        self.dispatcher.register("adb.screenshot_to_local", self.adb.screenshot_to_local, EmptyArgs)
        self.dispatcher.register("adb.qr_generate", self.qr.generate, QRGenerateArgs)
        self.dispatcher.register("adb.qr_terminal", self.qr.print_terminal_qr, QRTerminalArgs)
        self.dispatcher.register("task.schedule", self._schedule_prompt, TaskScheduleArgs)
        self.dispatcher.register("task.list", self._list_jobs, EmptyArgs)
        self.dispatcher.register("task.cancel", self._cancel_job, TaskCancelArgs)
        self.dispatcher.register("goal.run", self._run_goal, GoalRunArgs)
        self.dispatcher.register("goal.plan", self._plan_goal, GoalPlanArgs)
        self.dispatcher.register("goal.add", self._add_goal, GoalAddArgs)
        self.dispatcher.register("goal.list", self._list_goals, EmptyArgs)
        self.dispatcher.register("goal.cancel", self._cancel_goal, GoalCancelArgs)
        self.dispatcher.register("goal.resume", self._resume_goal, GoalResumeArgs)
        self.dispatcher.register("mcp.register_api_key", self._register_mcp_api_key, MCPRegisterKeyArgs)
        self.dispatcher.register("mcp.connect", self._connect_mcp, MCPConnectArgs)
        self.dispatcher.register("mcp.services", self._list_mcp_services, EmptyArgs)
        self.dispatcher.register("mcp.tools", self._list_mcp_tools, MCPListToolsArgs)
        self.dispatcher.register("mcp.call_tool", self._call_mcp_tool, MCPCallToolArgs)
        self.dispatcher.register("safety.emergency_stop", self._safety_emergency_stop, EmptyArgs)
        self.dispatcher.register("safety.clear_stop", self._safety_clear_stop, EmptyArgs)
        self.dispatcher.register("safety.status", self._safety_status, EmptyArgs)
        self.dispatcher.register("session.export", self._session_export_tool, ExportSessionArgs)
        self.dispatcher.register("assistant.set_mute", self._set_mute_tool, SetMuteArgs)
        self.dispatcher.register("assistant.mute_status", self._mute_status_tool, EmptyArgs)

    def _context_messages(self, user_text: str) -> tuple[str, list[dict], list[dict]]:
        session_id = self.session.current.session_id

        history = self.session.current.history
        if len(history) > self.trimmer.max_raw_turns:
            older = history[: -self.trimmer.max_raw_turns]
            snippet = " ".join(
                f"{turn.get('role', 'user')}: {turn.get('content', '').strip()}"
                for turn in older
                if turn.get("content")
            )
            if not hasattr(self, '_last_snippet_hash') or hash(snippet) != self._last_snippet_hash:
                self._last_snippet_hash = hash(snippet)
                thread = threading.Thread(
                    target=self._summarize_history_background,
                    args=(snippet, session_id),
                    daemon=True
                )
                thread.start()

        summary, recent = self.trimmer.trim(
            history,
            session_id=session_id,
            summarizer=self._summarize_history,
        )
        memories = self.memory.search(user_text, session_id=session_id, top_k=DEFAULT_MEMORY_TOP_K)
        world_state = snapshot_environment()

        if not settings.INCLUDE_CLIPBOARD_IN_CONTEXT:
            world_state.pop("clipboard", None)

        context_block = {
            "world_state": world_state,
            "relevant_memories": memories,
            "summary_of_older_turns": summary,
            "last_raw_turns": recent,
        }

        context_message = {
            "role": "system",
            "content": "Context payload:\n" + json.dumps(context_block, ensure_ascii=False),
        }

        system_prompt = build_system_prompt(
            self.base_system_prompt,
            dispatcher=self.dispatcher,
            emotion=self.emotion.state,
        )

        all_messages = [context_message, *recent]
        try:
            total_tokens = estimate_tokens_from_messages(all_messages)
            if total_tokens > 8000 and len(recent) > 2:
                keep_count = max(2, len(recent) - (total_tokens - 8000) // 500)
                recent = recent[-keep_count:]
                all_messages = [context_message, *recent]
        except Exception:
            pass

        return system_prompt, all_messages, memories

    def _summarize_history(self, text: str) -> str:
        """Summarize conversation history. Uses cached summary if available."""
        if not text.strip():
            return ""

        text_hash = hash(text)
        with self._summary_cache_lock:
            if text_hash in self._summary_cache:
                return self._summary_cache[text_hash]

        return text[:700]

    def _summarize_history_background(self, text: str, session_id: str) -> None:
        """Summarize history in background thread and update cache."""
        if not text.strip():
            return

        if not self._summarize_semaphore.acquire(blocking=False):
            return

        try:
            system = "Summarize the conversation history into a concise paragraph for future context."
            try:
                summary = self.engine.ask(prompt=text, system=system, history=[])
                with self._summary_cache_lock:
                    self._summary_cache[hash(text)] = summary
                self.trimmer.summaries[session_id] = summary
            except Exception:
                with self._summary_cache_lock:
                    self._summary_cache[hash(text)] = text[:700]
        finally:
            self._summarize_semaphore.release()

    def _apply_text_commands(self, user_text: str) -> str | None:
        text = user_text.strip().lower()
        if text in {"switch to work mode", "work mode"}:
            state = self.switch_session("jarvis_work")
            return f"Switched to {state.name} ({state.session_id})."
        if text in {"switch to personal mode", "personal mode"}:
            state = self.switch_session("jarvis_personal")
            return f"Switched to {state.name} ({state.session_id})."
        if text in {"reset context", "clear context"}:
            self.reset_context()
            return "Context reset for this session. Memories are still saved."
        if text in {"jarvis stop", "emergency stop", "stop now"}:
            guardrails.emergency_stop()
            return "Emergency stop is active. Tool execution is now blocked."
        if text in {"jarvis resume", "clear emergency stop", "resume tools"}:
            guardrails.clear_emergency_stop()
            return "Emergency stop cleared. Tool execution is enabled."
        if text in {"safety status", "emergency status"}:
            state = "active" if guardrails.is_emergency_stopped() else "inactive"
            return f"Emergency stop is {state}."
        if text in {"mute", "jarvis mute", "mute notifications"}:
            self.set_muted(True)
            return "Muted. Proactive alerts and autonomy notifications are silenced."
        if text in {"unmute", "jarvis unmute", "unmute notifications"}:
            self.set_muted(False)
            return "Unmuted. Proactive alerts and autonomy notifications are active."
        if text in {"toggle mute", "mute toggle"}:
            now_muted = self.toggle_mute()
            return "Muted." if now_muted else "Unmuted."
        if re.match(r"^switch session\s+.+$", text):
            name = user_text.strip().split(maxsplit=2)[-1]
            state = self.switch_session(name)
            return f"Switched to {state.name} ({state.session_id})."
        return None

    def ask_stream(
        self,
        user_text: str,
        *,
        allow_tools: bool = True,
        dry_run_tools: bool = False,
    ) -> Generator[str, None, None]:
        if self._hard_cap_hit:
            today = date.today()
            if self._hard_cap_hit_date != today:
                self._hard_cap_hit = False
                self._hard_cap_hit_date = None
            else:
                yield f"Daily token hard cap of {settings.DAILY_TOKEN_HARD_CAP} reached. Further calls blocked."
                return

        command_response = self._apply_text_commands(user_text)
        if command_response:
            yield command_response
            return

        self.emotion.update_from_signal(user_text)
        self.memory.set_online(NetworkState.is_online())
        if self.memory.online:
            self.memory.sync_all_pending()

        if needs_clarification(user_text):
            question = clarifying_question(user_text)
            self.session.add_turn("user", user_text)
            self.session.add_turn("assistant", question)
            yield question
            return

        system_prompt, history, _ = self._context_messages(user_text)
        self.session.add_turn("user", user_text)

        output_chunks: list[str] = []
        for token in self.engine.ask_stream(prompt=user_text, system=system_prompt, history=history):
            output_chunks.append(token)
            yield token

        assistant_text = "".join(output_chunks).strip()
        self._track_usage(system_prompt, history, user_text, assistant_text)
        tool_call = self.dispatcher.try_parse_tool_call(assistant_text) if allow_tools else None
        if tool_call:
            result = self.dispatcher.execute(tool_call, dry_run=dry_run_tools)
            tool_result_text = f"[tool_result] {json.dumps(result, ensure_ascii=False)}"
            if output_chunks:
                yield "\n"
            yield tool_result_text
            assistant_text = tool_result_text

        self.session.add_turn("assistant", assistant_text)
        self.memory.add(
            text=f"User: {user_text}\nAssistant: {assistant_text}",
            session_id=self.session.current.session_id,
            metadata={"source": "conversation"},
        )
        self.memory.sync_pending(self.session.current.session_id)

    def _track_usage(self, system_prompt: str, history: list[dict], user_text: str, assistant_text: str) -> None:
        input_tokens = estimate_tokens(system_prompt)
        input_tokens += estimate_tokens_from_messages(history)
        input_tokens += estimate_tokens(user_text)
        output_tokens = estimate_tokens(assistant_text)
        session_id = self.session.current.session_id
        provider = self.engine.last_provider
        self.usage.add(provider, input_tokens, output_tokens, session_id=session_id)
        today = date.today()
        total = self.usage.total_tokens_today(session_id=session_id)

        if self._hard_cap_hit_date != today:
            self._hard_cap_hit = False
            self._hard_cap_hit_date = None

        hard_cap = settings.DAILY_TOKEN_HARD_CAP
        if hard_cap > 0 and total >= hard_cap and not self._hard_cap_hit:
            self._hard_cap_hit = True
            self._hard_cap_hit_date = today
            msg = (
                f"[usage] HARD CAP REACHED: daily token usage {total} "
                f">= hard cap {hard_cap}. Further LLM calls are blocked for today."
            )
            print(msg)
            try:
                self._notify_telegram(msg)
            except Exception:
                pass

        if self._usage_alerted_day != today:
            if total >= settings.DAILY_TOKEN_ALERT_THRESHOLD:
                print(
                    f"\n[usage] Warning: daily token usage {total} "
                    f"exceeded threshold {settings.DAILY_TOKEN_ALERT_THRESHOLD}."
                )
                self._usage_alerted_day = today


def main() -> int:
    setup_logger()
    try:
        app = JarvisApp()
    except SettingsError as exc:
        print(str(exc))
        return 1

    def _shutdown_handler(*_):
        print("\n[signal] Shutdown signal received — cleaning up…")
        app.shutdown()
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, _shutdown_handler)
    signal.signal(signal.SIGINT, _shutdown_handler)

    try:
        run_cli(app)
    finally:
        app.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
