"""NOVA entry point."""

from __future__ import annotations

import json
import signal
import time
import hashlib
import ipaddress
import os
import socket
from pathlib import Path
import re
import threading
import sys
from collections import deque, OrderedDict
from typing import Any, Generator
from datetime import date
import copy
import queue
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from pydantic import BaseModel, Field

from config.constants import AGENT_NAME, DEFAULT_MEMORY_TOP_K, DEFAULT_SESSION_PERSONAL, DEFAULT_SESSION_WORK, DEFAULT_SYSTEM_PROMPT, MAX_CONTEXT_TOKENS
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
from core.think.reasoning import build_system_prompt, clarifying_question, detect_prompt_injection, needs_clarification
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
from tasks.goals import GoalResult, GoalRunner
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


class WebSearchArgs(BaseModel):
    query: str
    max_results: int = Field(default=5, ge=1, le=20)


class WebScrapeArgs(BaseModel):
    url: str


class WebCrawlArgs(BaseModel):
    seed_url: str
    max_pages: int = Field(default=5, ge=1, le=50)
    max_depth: int = Field(default=2, ge=0, le=10)


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
    max_depth: int = Field(default=8, ge=0, le=64)
    max_results: int = Field(default=500, ge=1, le=5000)


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



class GoalAddArgs(BaseModel):
    goal: str = Field(..., min_length=1, max_length=2000)
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


class NOVAApp:
    def __init__(self):
        # Pre-initialize shutdown-critical attributes so partial construction remains safe.
        self.health = None
        self.screen_watcher = None
        self.phone_watcher = None
        self.scheduler = None
        self.omniparser = None
        self.trimmer = ContextTrimmer(max_raw_turns=10)
        self._browser_lock = threading.RLock()
        self._emergency_hotkey_listener = None
        self._summarize_executor = ThreadPoolExecutor(max_workers=1)
        self._memory_executor = ThreadPoolExecutor(max_workers=1)
        self._sync_executor = ThreadPoolExecutor(max_workers=1)
        self._goal_plan_executor = ThreadPoolExecutor(max_workers=2)
        self.goal_runner = None
        self.autonomy_runner = None
        self._tts_queue = queue.Queue()
        self._tts_thread = threading.Thread(target=self._tts_worker, daemon=True)

        startup_phase = "cloud" if settings.has_cloud_llm else "minimal"
        settings.validate_startup(phase=startup_phase)

        self.dispatcher = Dispatcher()
        self.scheduler = TaskScheduler()
        self.master_api = MasterAPI()
        self.master_mcp = MasterMCP()
        self.session = SessionManager(
            default_name=settings.DEFAULT_SESSION,
            max_history_turns=settings.MAX_SESSION_HISTORY_TURNS,
        )
        self._muted = False
        self.trimmer = ContextTrimmer(max_raw_turns=10)
        self.health = HealthMonitor(on_change=self._handle_health_event)
        self.emotion = EmotionEngine()
        self.usage = UsageTracker(persist_path=".jarvis/usage_tracker.json")
        self._usage_alerted_day = None
        self._hard_cap_hit = False  # fix 7.1: set True when daily hard-cap is reached
        self._hard_cap_warning_day = None
        
        # Add tracking for daily resets (fix 1.5)
        self._hard_cap_hit_date: date | None = None
        self._usage_lock = threading.Lock()  # Fix 3: Lock around usage caps
        
        # Add summary cache tracking (fix 6.1, 11)
        self._summary_cache = OrderedDict()  # Fix 11
        self._summary_cache_lock = threading.Lock()  # fix 3.2
        self._last_snippet_hashes: dict[str, str] = {}
        self._summary_last_trigger_count: dict[str, int] = {}
        self._summary_retry_after: dict[str, float] = {}
        self._summary_submit_lock = threading.Lock()
        self._memory_submit_lock = threading.Lock()
        self._goal_plan_submit_lock = threading.Lock()
        self._summary_inflight: set[str] = set()

        # Add single thread for TTS execution (fix 5.1)
        self._tts_thread.start()

        # Separate executors so goal planning and memory sync cannot block summarization.
        self._max_background_summary_jobs = 100
        self._max_background_memory_jobs = 200
        self._max_goal_plan_jobs = 50
        self._summary_jobs_inflight = 0
        self._memory_jobs_inflight = 0
        self._goal_plan_jobs_inflight = 0
        self._shutting_down = threading.Event()
        self._max_pending_goals = 20
        self._health_http_server: ThreadingHTTPServer | None = None
        self._health_http_thread: threading.Thread | None = None

        self._event_lock = threading.Lock()
        self._events = deque(maxlen=100)
        self.memory = MemoryRouter(
            mem0=Mem0Client(api_key=settings.MEM0_API_KEY),
            local=LocalMemoryStore(),
        )
        self.docs = DocumentStore()
        self._browser: Browser | None = None
        self._browser_lock = threading.RLock()
        self._mouse_keyboard: Any | None = None
        self._omniparser_client: Any | None = None
        # Fix 7: ADB client connection validation
        import shutil
        if shutil.which("adb"):
            self.adb = ADBClient()
            self.health.register_subsystem(
                "adb",
                check_fn=lambda: __import__("subprocess").run(["adb", "version"], capture_output=True).returncode == 0,
            )
        else:
            self.adb = None
            self.health.register_subsystem("adb", check_fn=lambda: False)
            
        if not settings.ALLOWED_PHONE_NUMBERS and settings.AUTONOMY_ENABLED:
            import logging
            logging.getLogger(__name__).warning("ALLOWED_PHONE_NUMBERS is empty — adb.send_sms will always be blocked")
        self.qr = QRPairing(adb_port=settings.ADB_PORT)
        self.omniparser = OmniParserServer(
            url=settings.OMNIPARSER_SERVER_URL,
            repo_dir=settings.OMNIPARSER_REPO_DIR,
        )
        Path("assets").mkdir(parents=True, exist_ok=True)
        Path("exports").mkdir(parents=True, exist_ok=True)
        self._goals_file = Path(".jarvis/nova_goals.json")
        self._goals_file.parent.mkdir(parents=True, exist_ok=True)
        self._goals: list[dict] = []
        if self._goals_file.exists():
            try:
                self._goals = json.loads(self._goals_file.read_text(encoding="utf-8"))
                for goal in self._goals:
                    if goal.get("status") in {"planning", "running"}:
                        goal["status"] = "pending"
            except Exception as exc:
                import logging
                logging.getLogger(__name__).warning(
                    "Failed to load goals from %s: %s — starting with empty list",
                    self._goals_file, exc
                )
        self._goal_lock = threading.Lock()
        self._goal_persist_lock = threading.Lock()
        self._goal_persist_timer: threading.Timer | None = None
        self._goal_persist_interval_seconds = 0.5
        self._autonomy_stop = threading.Event()
        self._autonomy_thread: threading.Thread | None = None
        self._barge_in_event = threading.Event()
        self._autonomy_start_lock = threading.Lock()
        self._boot_time = time.monotonic()
        self._emergency_hotkey_listener: Any | None = None
        self.screen_watcher = ScreenWatcher(
            interval_seconds=settings.PROACTIVE_WATCHER_INTERVAL,
            cooldown_seconds=settings.PROACTIVE_WATCHER_COOLDOWN,
            on_alert=self._handle_proactive_alert,
            omniparser_url=settings.OMNIPARSER_SERVER_URL,
        )
        self.phone_watcher = None
        if self.adb is not None:
            self.phone_watcher = PhoneWatcher(adb=self.adb, on_alert=self._handle_proactive_alert)
        elif settings.PHONE_WATCHER_ENABLED:
            import logging
            logging.getLogger(__name__).warning("PHONE_WATCHER_ENABLED=true but ADB is unavailable; disabling phone watcher.")
        self.engine = LLMEngine(
            openai_base_url=settings.OPENAI_BASE_URL or "http://localhost:11434",
            openai_keys=settings.OPENAI_API_KEYS,
            ollama_base_url=settings.OLLAMA_BASE_URL,
            ollama_model=settings.OLLAMA_MODEL,
        )
        self.base_system_prompt = DEFAULT_SYSTEM_PROMPT
        self._register_builtin_tools()
        
        # Separate manual-goal execution from autonomy-goal execution to avoid cross-blocking.
        self._goal_execution_lock = threading.Semaphore(1)
        self._autonomy_execution_lock = threading.Semaphore(1)
        self.goal_runner = GoalRunner(
            self.dispatcher,
            confirm_callback=self._interactive_confirm,
            force_confirm_medium=False,
            step_timeout_seconds=settings.GOAL_STEP_TIMEOUT_SECONDS,
        )

        def _autonomy_confirm(prompt: str) -> bool:
            if settings.AUTONOMY_NOTIFY_TELEGRAM:
                self._notify_telegram(f"Autonomy paused for high-risk step.\n{prompt}\nReply with: /approve_goal")
            return False

        self._autonomy_confirm_callback = _autonomy_confirm
        self.autonomy_runner = GoalRunner(
            self.dispatcher,
            confirm_callback=self._autonomy_confirm_callback,
            force_confirm_medium=True,
            step_delay_seconds=max(0.1, float(settings.AUTONOMY_STEP_DELAY_SECONDS)),
            step_timeout_seconds=settings.GOAL_STEP_TIMEOUT_SECONDS,
        )
        self._last_sync_all_pending = 0.0
        self._sync_all_inflight = False
        self._sync_all_lock = threading.Lock()

        if settings.PLUGINS_ENABLED:
            try:
                load_plugins(self.dispatcher)
            except Exception as exc:
                import logging
                logging.getLogger(__name__).warning("Plugin loader failed: %s", exc)
        try:
            self._start_health_monitoring()
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("Health monitoring startup failed: %s", exc)
        try:
            self._start_watchers_if_enabled()
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("Watcher startup failed: %s", exc)
        try:
            self._start_autonomy_loop()
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("Autonomy loop startup failed: %s", exc)
        try:
            self._start_emergency_hotkey()
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("Emergency hotkey startup failed: %s", exc)
        try:
            self._start_probe_server()
        except Exception as exc:
            import logging
            logging.getLogger(__name__).error("Health probe startup failed: %s", exc)
        try:
            self.scheduler.start()
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("Scheduler startup failed: %s", exc)
        # Missing feature fix: schedule daily ChromaDB backup to prevent data loss on corruption
        try:
            if self.scheduler.scheduler.running:
                from core.memory.backup import schedule_daily_backup
                schedule_daily_backup(self.scheduler)
            else:
                import logging
                logging.getLogger(__name__).warning("Skipping backup registration because scheduler is not running.")
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("Failed to schedule ChromaDB backup: %s", exc)

    def last_provider_label(self) -> str:
        return self.engine.last_provider

    @property
    def emotion_state(self) -> str:
        return self.emotion.state

    def switch_session(self, name: str):
        state = self.session.switch(name)
        # Session isolation: reset stateful tool clients on session switch.
        with self._browser_lock:
            self._browser_close()
        self._mouse_keyboard = None
        if getattr(self, "adb", None):
            try:
                self.adb.device = None
            except Exception:
                pass
        return state

    def reset_context(self) -> None:
        """Clear current session history and the associated trimmer summary (fix 1.6).

        Also auto-exports as a backup before clearing (fix 7.4).
        """
        session_id = self.session.current.session_id
        # fix 7.4: auto-backup session before clearing
        try:
            session = self.session.current
            with session._lock:
                history_snapshot = list(session.history)
            self.export_session("md", history=history_snapshot)
        except Exception:
            pass
        self.session.reset_context()
        # fix 1.6: clear the stale summary so it doesn't bleed into the new context
        with self.trimmer._lock:
            self.trimmer.summaries.pop(session_id, None)
            self.trimmer._last_summarized_count.pop(session_id, None)
        with self._summary_submit_lock:
            self._summary_last_trigger_count.pop(session_id, None)
            self._summary_retry_after.pop(session_id, None)
            self._last_snippet_hashes.pop(session_id, None)

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

    def export_session(self, fmt: str = "md", history: list[dict] | None = None) -> str:
        session = self.session.current
        timestamp = int(time.time())
        safe_name = re.sub(r"[^a-zA-Z0-9_-]+", "_", session.name).strip("_") or "session"
        payload = history if history is not None else session.history
        if fmt.lower() == "json":
            path = f"exports/{safe_name}_{timestamp}.json"
            return export_json(payload, path)
        path = f"exports/{safe_name}_{timestamp}.md"
        return export_markdown(payload, path)

    def status_text(self) -> str:
        health_items = self.health.status_table()
        return json.dumps(
            {
                "session": self.session.current.name,
                "session_id": self.session.current.session_id,
                "active_cloud_keys": self.engine.pool.active_count() if self.engine.pool else 0,
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
                "summary_jobs_inflight": self._summary_jobs_inflight,
                "memory_jobs_inflight": self._memory_jobs_inflight,
                "goal_plan_jobs_inflight": self._goal_plan_jobs_inflight,
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
            # Fix 2.2: ensure token stays updated across server restarts
            if self._omniparser_client.auth_token != current_token:
                self._omniparser_client.auth_token = current_token
                try:
                    from vision.omniparser import clear_ui_element_cache
                    clear_ui_element_cache()
                except Exception:
                    pass
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
        with self._browser_lock:
            self._get_browser().open(url)
        return f"opened {url}"

    def _browser_click(self, selector: str) -> str:
        with self._browser_lock:
            self._get_browser().click(selector)
        return f"clicked {selector}"

    def _browser_fill(self, selector: str, value: str) -> str:
        with self._browser_lock:
            self._get_browser().fill(selector, value)
        return f"filled {selector}"

    def _browser_extract_text(self) -> str:
        with self._browser_lock:
            return self._get_browser().extract_text()

    def _browser_get_links(self) -> list[str]:
        with self._browser_lock:
            return self._get_browser().get_links()

    def _browser_wait_for_text(self, text: str, timeout_ms: int = 10_000) -> bool:
        with self._browser_lock:
            return self._get_browser().wait_for_text(text, timeout_ms=timeout_ms)

    def _browser_screenshot(self, path: str = "assets/browser_screen.png") -> str:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with self._browser_lock:
            self._get_browser().screenshot(path=str(target))
        return str(target)

    def _browser_close(self) -> str:
        with self._browser_lock:
            if self._browser is None:
                return "browser not running"
            self._browser.close()
            self._browser = None
            return "browser closed"

    def _schedule_prompt(self, schedule_text: str, prompt: str, job_id: str | None = None) -> dict:
        job_id = job_id or f"job_{int(time.time())}"

        def _run(p=prompt, jid=job_id) -> None:
            response = "".join(
                self.ask_stream(
                    p,
                    allow_tools=False,
                )
            )
            print(f"\n[scheduled:{jid}] {response}")
            # Bug fix: scheduled tasks now notify via Telegram/TTS (previously silent)
            self._notify_autonomy_event(f"[scheduled:{jid}] {response}")

        try:
            cron = self.scheduler.add_from_text(_run, schedule_text, job_id=job_id)
            return {"job_id": job_id, "schedule": cron}
        except ValueError as exc:
            return {"status": "error", "reason": str(exc), "job_id": job_id}

    def _list_jobs(self) -> list[dict]:
        return self.scheduler.list_jobs_detailed()

    def _cancel_job(self, job_id: str) -> dict:
        ok = self.scheduler.remove_job(job_id)
        return {"job_id": job_id, "status": "cancelled" if ok else "not_found"}

    def _run_goal(self, goal: str, steps: list[GoalStepArgs], max_steps: int = 20, dry_run: bool = False) -> dict:
        step_dicts = [{"tool": step.tool, "args": step.args} for step in steps]
        with self._goal_execution_lock:
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
            if isinstance(data, str):
                try:
                    data = json.loads(data)
                except json.JSONDecodeError:
                    return []
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

        raw = ""
        steps = []
        for attempt in range(3):
            raw = self.engine.ask(prompt=f"Goal: {goal}", system=system_prompt, history=[])
            self._track_usage(system_prompt, [], f"[goal_plan] {goal}", raw)
            steps = _extract_steps(raw)
            if steps:
                break
            system_prompt += "\nCRITICAL ERROR: Your previous response was not a valid JSON list. You MUST return ONLY a JSON list of tool objects."

        if not steps:
            return {"goal": goal, "status": "failed", "reason": "no_steps_parsed", "raw": raw}
        if len(steps) > max_steps:
            steps = steps[:max_steps]
        return {"goal": goal, "status": "ok", "steps": steps, "raw": raw}
        
    def _add_goal(self, goal: str, max_steps: int = 20) -> dict:
        goal = re.sub(r"\s+", " ", goal).strip()
        if len(goal) > 500:
            goal = goal[:500].rstrip() + "..."
        if detect_prompt_injection(goal):
            return {"status": "error", "reason": "goal_rejected_prompt_injection"}
        with self._goal_lock:
            pending_count = sum(1 for g in self._goals if g.get("status") in {"planning", "pending"})
            if pending_count >= self._max_pending_goals:
                return {
                    "status": "error",
                    "reason": f"too_many_pending_goals:max={self._max_pending_goals}",
                }
        goal_id = f"goal_{int(time.time())}"
        record = {
            "id": goal_id,
            "goal": goal,
            "steps": [],
            "status": "planning",
            "created_at": time.time(),
            "max_steps": max_steps,
            "cursor": 0,
        }
        with self._goal_lock:
            self._goals.append(record)
            self._persist_goals()
        with self._goal_plan_submit_lock:
            if self._goal_plan_jobs_inflight >= self._max_goal_plan_jobs:
                with self._goal_lock:
                    for item in self._goals:
                        if item.get("id") == goal_id:
                            item["status"] = "failed"
                            item["last_result"] = {"status": "failed", "reason": "goal_planning_queue_full"}
                            self._persist_goals()
                            break
                return {"status": "error", "reason": "goal_planning_queue_full", "id": goal_id}

        def background_plan():
            with self._goal_plan_submit_lock:
                self._goal_plan_jobs_inflight += 1
            if self._shutting_down.is_set():
                with self._goal_plan_submit_lock:
                    self._goal_plan_jobs_inflight = max(0, self._goal_plan_jobs_inflight - 1)
                return
            try:
                plan = self._plan_goal(goal, max_steps=min(max_steps, 30))
            except Exception as exc:
                plan = {"status": "failed", "reason": f"planning_exception:{exc}"}
            if self._shutting_down.is_set():
                with self._goal_plan_submit_lock:
                    self._goal_plan_jobs_inflight = max(0, self._goal_plan_jobs_inflight - 1)
                return
            with self._goal_lock:
                for item in self._goals:
                    if item.get("id") == goal_id:
                        if plan.get("status") == "ok":
                            item["steps"] = plan["steps"]
                            item["status"] = "pending"
                        else:
                            item["status"] = "failed"
                            item["last_result"] = plan
                        self._persist_goals()
                        break
            with self._goal_plan_submit_lock:
                self._goal_plan_jobs_inflight = max(0, self._goal_plan_jobs_inflight - 1)

        future = self._goal_plan_executor.submit(background_plan)
        def _on_done(fut):
            try:
                fut.result()
            except Exception as exc:
                with self._goal_lock:
                    for item in self._goals:
                        if item.get("id") == goal_id and item.get("status") == "planning":
                            item["status"] = "failed"
                            item["last_result"] = {"status": "failed", "reason": f"planning_future_exception:{exc}"}
                            self._persist_goals()
                            break
                with self._goal_plan_submit_lock:
                    self._goal_plan_jobs_inflight = max(0, self._goal_plan_jobs_inflight - 1)
        future.add_done_callback(_on_done)
        return record

    def _on_goal_step_completed(self, goal_id: str, step_index: int, step_result: dict[str, Any]) -> None:
        with self._goal_lock:
            for item in self._goals:
                if item.get("id") != goal_id:
                    continue
                item["cursor"] = step_index + 1
                item["last_step_result"] = step_result
                item["updated_at"] = time.time()
                self._persist_goals_debounced()
                break

    def _doc_ingest(self, filepath: str) -> dict:
        raw = filepath.strip()
        if ".." in raw.replace("\\", "/").split("/"):
            return {"status": "error", "reason": "path_traversal_blocked"}
        target = Path(raw).expanduser().resolve()
        protected_prefixes = [Path("/etc"), Path("/proc"), Path("/sys"), Path("/dev")]
        if any(str(target).startswith(str(p)) for p in protected_prefixes):
            return {"status": "error", "reason": "path_not_allowed"}
        allowed_roots = [
            Path(os.getenv("NOVA_DOCS_ROOT", str(Path.cwd()))).expanduser().resolve(),
            Path.home().resolve(),
            Path(Path(os.getenv("TMPDIR", "/tmp")).resolve()),
        ]
        if not any(str(target).startswith(str(root)) for root in allowed_roots):
            return {"status": "error", "reason": "path_outside_allowed_roots"}
        return self.docs.ingest(str(target))

    def _persist_goals(self) -> None:
        try:
            import tempfile
            payload = json.dumps(self._goals, ensure_ascii=False, indent=2)
            self._goals_file.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=str(self._goals_file.parent),
                delete=False,
                suffix=".tmp",
            ) as tmp:
                tmp.write(payload)
                tmp.flush()
                tmp_path = Path(tmp.name)
            tmp_path.replace(self._goals_file)
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning("Failed to persist goals: %s", e)

    def _persist_goals_debounced(self) -> None:
        with self._goal_persist_lock:
            if self._goal_persist_timer and self._goal_persist_timer.is_alive():
                return

            def _flush() -> None:
                with self._goal_persist_lock:
                    self._goal_persist_timer = None
                with self._goal_lock:
                    self._persist_goals()

            timer = threading.Timer(self._goal_persist_interval_seconds, _flush)
            timer.daemon = True
            self._goal_persist_timer = timer
            timer.start()

    def _list_goals(self) -> list[dict]:
        with self._goal_lock:
            return [dict(item) for item in self._goals]

    def _cancel_goal(self, goal_id: str) -> dict:
        with self._goal_lock:
            for item in self._goals:
                if item.get("id") == goal_id:
                    if item.get("status") == "pending":
                        item["status"] = "cancelled"
                        self._persist_goals()
                        return {"goal_id": goal_id, "status": "cancelled"}
                    return {"goal_id": goal_id, "status": "not_pending"}
        return {"goal_id": goal_id, "status": "not_found"}

    def _resume_goal(self, goal_id: str) -> dict:
        with self._goal_lock:
            for item in self._goals:
                if item.get("id") == goal_id:
                    if item.get("status") in {"paused", "failed"}:
                        item["status"] = "pending"
                        self._persist_goals()
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
        def _resolve_host_with_timeout(hostname: str, timeout_seconds: float = 5.0) -> list[str]:
            from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
            import socket as _socket

            def _run() -> list[str]:
                rows = _socket.getaddrinfo(hostname, None)
                return [r[4][0] for r in rows]

            pool = ThreadPoolExecutor(max_workers=1)
            fut = pool.submit(_run)
            try:
                return fut.result(timeout=timeout_seconds)
            except FuturesTimeout:
                fut.cancel()
                return []
            finally:
                try:
                    pool.shutdown(wait=False, cancel_futures=True)
                except TypeError:
                    pool.shutdown(wait=False)

        svc = service.strip().lower()
        if not svc:
            return {"status": "error", "reason": "service_required"}

        key = (api_key or "").strip() or (self.master_api.get(svc) or "")
        if endpoint:
            # Security fix (4.3): Never inject an Authorization Bearer token over plain HTTP.
            # If a key is present and the endpoint is not HTTPS or localhost, reject it.
            parsed_scheme, parsed_host = "", ""
            try:
                from urllib.parse import urlparse
                parsed = urlparse(endpoint)
                parsed_scheme = parsed.scheme.lower()
                parsed_host = (parsed.hostname or "").lower()
            except Exception:
                pass
            is_local = parsed_host in {"localhost", "127.0.0.1", "::1"}
            if key and parsed_scheme == "http":
                resolved_private = False
                try:
                    addrs = set(_resolve_host_with_timeout(parsed_host, timeout_seconds=5.0))
                    if not addrs:
                        return {
                            "status": "error",
                            "reason": "dns_resolution_timeout_or_failure",
                        }
                    resolved_private = True
                    for ip in addrs:
                        parsed_ip = ipaddress.ip_address(ip)
                        mapped = getattr(parsed_ip, "ipv4_mapped", None)
                        if mapped is not None:
                            parsed_ip = mapped
                        if not (parsed_ip.is_private or parsed_ip.is_loopback):
                            resolved_private = False
                            break
                except Exception:
                    return {
                        "status": "error",
                        "reason": "dns_resolution_timeout_or_failure",
                    }
                if not (is_local or resolved_private):
                    return {
                        "status": "error",
                        "reason": (
                            "Refusing to inject Authorization header over plain HTTP. "
                            "Use an HTTPS endpoint or a local/private address."
                        ),
                    }
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
        self.health.register_subsystem("nova", lambda: True)
        self.health.register_subsystem("network", lambda: NetworkState.is_online())
        self.health.register_subsystem("memory_router", lambda: self.memory is not None)
        self.health.register_subsystem(
            "mem0_client",
            lambda: (
                not bool(settings.MEM0_API_KEY)
                or not bool(getattr(self.memory.mem0, "_remote_enabled", False))
                or bool(self.memory.mem0.get_all(self.session.current.session_id) is not None)
            ),
        )
        self.health.register_subsystem(
            "scheduler",
            lambda: bool(getattr(self.scheduler, "scheduler", None) and self.scheduler.scheduler.running),
            restart_fn=self.scheduler.start,
        )
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
        # Critical fix (5.3): Register LLM engine health — previously Ollama crashes had
        # no health check, so failures were silent with no auto-restart attempted.
        def _check_llm_engine() -> bool:
            if (time.monotonic() - self._boot_time) < 90:
                return True
            try:
                import requests as _req
                base = settings.OLLAMA_BASE_URL.rstrip("/")
                for path in ("/api/tags", "/health", "/v1/models"):
                    try:
                        resp = _req.get(f"{base}{path}", timeout=5)
                        if resp.ok:
                            return True
                    except Exception:
                        continue
                return False
            except Exception:
                return False

        def _restart_llm_engine() -> None:
            import subprocess as _sp
            try:
                _sp.Popen(["ollama", "serve"], stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)
            except Exception:
                pass

        self.health.register_subsystem(
            "llm_engine",
            check_fn=_check_llm_engine,
            restart_fn=_restart_llm_engine,
        )
        if settings.PROACTIVE_WATCHER_ENABLED:
            self.health.register_subsystem(
                "screen_watcher",
                check_fn=self.screen_watcher.is_running,
                restart_fn=self.screen_watcher.restart,
            )
        if settings.PHONE_WATCHER_ENABLED and self.phone_watcher is not None:
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
        self.health.register_subsystem(
            "probe_server",
            check_fn=lambda: self._health_http_server is not None and self._health_http_thread is not None and self._health_http_thread.is_alive(),
            restart_fn=self._start_probe_server,
        )
        try:
            self.omniparser.ensure_running()
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("OmniParser startup check failed: %s", exc)
        self.health.start(interval_seconds=settings.HEALTH_MONITOR_INTERVAL)

    def _start_watchers_if_enabled(self) -> None:
        if settings.PROACTIVE_WATCHER_ENABLED:
            try:
                self.screen_watcher.start()
            except Exception:
                pass
        if settings.PHONE_WATCHER_ENABLED and self.phone_watcher is not None:
            try:
                self.phone_watcher.start()
            except Exception:
                pass

    def _autonomy_is_running(self) -> bool:
        return self._autonomy_thread is not None and self._autonomy_thread.is_alive()

    def _start_autonomy_loop(self) -> None:
        with self._autonomy_start_lock:
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

            self._emergency_hotkey_listener = keyboard.GlobalHotKeys({hotkey_str: self._barge_in_event.set})
            self._emergency_hotkey_listener.start()
        except Exception:
            self._emergency_hotkey_listener = None

    def _stop_autonomy_loop(self) -> None:
        self._autonomy_stop.set()
        if self._autonomy_thread and self._autonomy_thread.is_alive():
            timeout = max(2.0, float(getattr(settings, "GOAL_STEP_TIMEOUT_SECONDS", 60.0)) + 2.0)
            self._autonomy_thread.join(timeout=timeout)

    def _start_probe_server(self) -> None:
        if self._health_http_server is not None:
            return

        app = self

        class _ProbeHandler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                if self.path.rstrip("/") not in {"/health", "/ready"}:
                    self.send_response(404)
                    self.end_headers()
                    return
                status = b'{"status":"ok"}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(status)))
                self.end_headers()
                self.wfile.write(status)

            def log_message(self, format, *args):  # noqa: A003
                _ = (app, format, args)
                return

        server = ThreadingHTTPServer((str(settings.NOVA_HEALTH_BIND_HOST), int(settings.NOVA_HEALTH_PORT)), _ProbeHandler)
        server.daemon_threads = True
        self._health_http_server = server
        self._health_http_thread = threading.Thread(target=server.serve_forever, daemon=True)
        self._health_http_thread.start()

    def _stop_probe_server(self) -> None:
        if self._health_http_server is None:
            return
        try:
            self._health_http_server.shutdown()
            self._health_http_server.server_close()
        except Exception:
            pass
        if self._health_http_thread and self._health_http_thread.is_alive():
            self._health_http_thread.join(timeout=2)
        self._health_http_server = None
        self._health_http_thread = None

    def _autonomy_loop(self) -> None:
        poll = max(2.0, float(settings.AUTONOMY_POLL_SECONDS))
        while not self._autonomy_stop.is_set():
            goal = None
            # Deep copy to avoid reading mutable dict references outside the lock.
            with self._goal_lock:
                goals_snapshot = copy.deepcopy(self._goals)
                
            candidate_id = None
            for item in goals_snapshot:
                if item.get("status") in {"pending", "approved_for_step"} and item.get("steps"):
                    candidate_id = item.get("id")
                    break
                    
            if candidate_id:
                with self._goal_lock:
                    for item in self._goals:
                        if item.get("id") != candidate_id:
                            continue
                        if item.get("status") == "cancelled":
                            goal = None
                            break
                        if item.get("status") in {"pending", "approved_for_step"} and item.get("steps"):
                            # If it was specifically approved, we will pass a flag down
                            goal = copy.deepcopy(item)
                            item["status"] = "running"
                            item["started_at"] = time.time()
                            break
            if not goal:
                self._autonomy_stop.wait(min(1.0, poll))
                continue

            steps = goal.get("steps") or []
            max_steps = int(goal.get("max_steps") or settings.AUTONOMY_MAX_STEPS)
            start_index = int(goal.get("cursor") or 0)
            
            approved_for_step = goal.get("status") == "approved_for_step"
            with self._autonomy_execution_lock:
                with self._goal_lock:
                    current = next((g for g in self._goals if g.get("id") == goal.get("id")), None)
                    if current and current.get("status") == "cancelled":
                        continue
                if approved_for_step:
                    if start_index >= len(steps):
                        result = GoalResult(status="completed", reason="no_remaining_steps", results=[], next_index=len(steps))
                    else:
                        result = self.autonomy_runner.run(
                            steps[start_index : start_index + 1],
                            max_steps=1,
                            start_index=0,
                            on_step=lambda i, r, gid=goal.get("id"): self._on_goal_step_completed(str(gid), i, r),
                            confirm_callback=lambda _p: True,
                        )
                        result.next_index = min(len(steps), start_index + (1 if result.status == "completed" else 0))
                else:
                    result = self.autonomy_runner.run(
                        steps,
                        max_steps=max_steps,
                        start_index=start_index,
                        on_step=lambda i, r, gid=goal.get("id"): self._on_goal_step_completed(str(gid), i, r),
                        confirm_callback=self._autonomy_confirm_callback,
                    )

            if approved_for_step and result.status == "completed":
                status = "pending" if result.next_index < len(steps) else "completed"
            else:
                status = "completed" if result.status == "completed" else "paused"
                if result.status == "stopped" and "Cycle detected" in result.reason:
                    status = "failed"
                if result.status == "stopped" and "max_steps" in result.reason:
                    status = "paused"
                if result.status == "failed":
                    status = "failed"
                if result.status == "blocked":
                    status = "awaiting_confirmation"

            if self._shutting_down.is_set():
                break

            with self._goal_lock:
                for item in self._goals:
                    if item.get("id") == goal.get("id"):
                        # Bug fix: Check if a cancel arrived between "running" and this write block.
                        # If user already set it to "cancelled", respect that and skip overwriting.
                        if item.get("status") == "cancelled":
                            break
                        item["status"] = status
                        item["cursor"] = min(int(result.next_index), len(steps))
                        item["finished_at"] = time.time()
                        item["last_result"] = {
                            "status": result.status,
                            "reason": result.reason,
                            "results": result.results,
                            "next_index": result.next_index,
                        }
                        self._persist_goals()
                        break

            if self._shutting_down.is_set():
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
            if not self._shutting_down.is_set():
                self.session.add_turn("assistant", message)
            self._notify_autonomy_event(message)

    def shutdown(self) -> None:
        self._shutting_down.set()
        if getattr(self, "health", None):
            self.health.stop()
        if settings.PROACTIVE_WATCHER_ENABLED:
            if getattr(self, "screen_watcher", None):
                self.screen_watcher.stop()
        phone_watcher = getattr(self, "phone_watcher", None)
        if settings.PHONE_WATCHER_ENABLED and phone_watcher is not None:
            phone_watcher.stop()
        if getattr(self, "scheduler", None):
            self.scheduler.stop()
        try:
            with self._goal_persist_lock:
                timer = self._goal_persist_timer
                self._goal_persist_timer = None
            if timer and timer.is_alive():
                timer.cancel()
            with self._goal_lock:
                self._persist_goals()
        except Exception:
            pass
        self._stop_autonomy_loop()
        self._stop_probe_server()
        if self._emergency_hotkey_listener is not None:
            try:
                self._emergency_hotkey_listener.stop()
            except Exception:
                pass
        if getattr(self, "_browser_lock", None):
            with self._browser_lock:
                self._browser_close()
        try:
            self.omniparser.stop()
        except Exception:
            pass
        try:
            self.usage.flush()
        except Exception:
            pass
        try:
            summary_file = Path(".jarvis/trimmer_summaries.json")
            summary_file.parent.mkdir(parents=True, exist_ok=True)
            with self.trimmer._lock:
                summary_file.write_text(
                    json.dumps(self.trimmer.summaries, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
        except Exception:
            pass
        lock_acquired = False
        try:
            lock_acquired = self._autonomy_execution_lock.acquire(timeout=5)
        except Exception:
            lock_acquired = False
        try:
            self.goal_runner.close()
            self.autonomy_runner.close()
        except Exception:
            pass
        finally:
            if lock_acquired:
                try:
                    self._autonomy_execution_lock.release()
                except Exception:
                    pass
        import sys as _sys
        kwargs = {"cancel_futures": True} if _sys.version_info >= (3, 9) else {}
        self._summarize_executor.shutdown(wait=False, **kwargs)
        self._memory_executor.shutdown(wait=False, **kwargs)
        self._sync_executor.shutdown(wait=False, **kwargs)
        self._goal_plan_executor.shutdown(wait=False, **kwargs)
        # Bug fix: drain TTS queue on shutdown so the worker thread exits cleanly
        try:
            self._tts_queue.put(None)   # sentinel to stop the worker
            self._tts_thread.join(timeout=5)
        except Exception:
            pass

    def __del__(self):
        return

    def _handle_proactive_alert(self, message: str) -> None:
        if "potentially malicious on-screen text" in message.lower():
            self.record_event("security", message)
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
            self._notify_telegram(message)

    def _notify_telegram(self, text: str) -> dict | None:
        if not settings.AUTONOMY_NOTIFY_TELEGRAM:
            return None
        try:
            result = send_telegram_text(
                bot_token=settings.TELEGRAM_BOT_TOKEN,
                chat_id=settings.TELEGRAM_CHAT_ID,
                text=text,
            )
            # Fix 8: Telegram notifications have no error surface
            if not result.get("ok"):
                self.record_event("health", f"Telegram API failed: {result}")
            return result
        except Exception as exc:
            self.record_event("health", f"Telegram emit threw exception: {exc}")
            return None

    def _tts_worker(self) -> None:
        """Fix 5.1: TTS executed on a single dedicated background thread."""
        try:
            from voice.tts_offline import speak as speak_offline
        except Exception:
            speak_offline = None
            
        while True:
            text = self._tts_queue.get()
            if text is None:
                self._tts_queue.task_done()
                break
                
            if speak_offline is None:
                self._tts_queue.task_done()
                continue
                
            # Fix 23: Add watchdog for TTS worker thread
            def run_speak():
                try:
                    speak_offline(text)
                except Exception:
                    pass
                    
            worker = threading.Thread(target=run_speak, daemon=True)
            worker.start()
            worker.join(timeout=settings.TTS_OFFLINE_WATCHDOG_SECONDS)
            if worker.is_alive():
                print(f"[tts] Warning: TTS worker hung after {settings.TTS_OFFLINE_WATCHDOG_SECONDS}s, dropping item.")
            
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
        self.dispatcher.register("doc.ingest", self._doc_ingest, DocIngestArgs)
        self.dispatcher.register("doc.query", self.docs.query, DocQueryArgs)
        self.dispatcher.register(
            "doc.list",
            self.docs.list_docs,
            EmptyArgs,
            description="List ingested documents with filename and metadata.",
        )
        self.dispatcher.register("session.switch", lambda name: self.switch_session(name).name, SessionSwitchArgs)
        self.dispatcher.register("win32_api.read", win32_api.read_file, FileReadArgs)
        self.dispatcher.register("win32_api.write", win32_api.write_file, FileWriteArgs)
        self.dispatcher.register("win32_api.move", win32_api.move_file, FileMoveArgs)
        self.dispatcher.register("win32_api.delete", win32_api.delete_file, FileDeleteArgs)
        self.dispatcher.register(
            "win32_api.list_processes",
            win32_api.list_processes,
            EmptyArgs,
            description="List currently running local processes as names/identifiers.",
        )
        self.dispatcher.register("win32_api.search", win32_api.search_files, FileSearchArgs)
        self.dispatcher.register("win32_api.copy", win32_api.copy_file, FileMoveArgs)
        self.dispatcher.register("win32_api.kill_process", win32_api.kill_process, ProcessKillArgs)
        self.dispatcher.register("win32_api.launch_process", win32_api.launch_process, ProcessLaunchArgs)
        self.dispatcher.register("win32_api.get_clipboard", win32_api.get_clipboard, EmptyArgs)
        self.dispatcher.register("win32_api.set_clipboard", win32_api.set_clipboard, ClipboardSetArgs)
        self.dispatcher.register("win32_api.disk_info", win32_api.disk_info, DiskInfoArgs)
        if sys.platform.startswith("win"):
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
        if getattr(self, "adb", None):
            self.dispatcher.register("adb.connect", self.adb.connect, ADBConnectArgs)
            self.dispatcher.register("adb.devices", self.adb.devices, EmptyArgs)
            self.dispatcher.register("adb.tap", self.adb.tap, ADBTapArgs)
            self.dispatcher.register("adb.swipe", self.adb.swipe, ADBSwipeArgs)
            self.dispatcher.register("adb.type_text", self.adb.type_text, ADBTextArgs)
            self.dispatcher.register("adb.launch_app", self.adb.launch_app, ADBLaunchArgs)
            self.dispatcher.register("adb.keyevent", self.adb.keyevent, ADBKeyEventArgs)
            self.dispatcher.register("adb.pull", self.adb.pull, ADBPullArgs)
            self.dispatcher.register("adb.push", self.adb.push, ADBPushArgs)
            self.dispatcher.register("adb.send_sms", self._adb_send_sms, ADBSmsArgs)
            self.dispatcher.register(
                "adb.notifications_dump",
                self.adb.notifications_dump,
                EmptyArgs,
                description="Dump recent Android notifications as text.",
            )
            self.dispatcher.register(
                "adb.sms_dump",
                self.adb.sms_dump,
                EmptyArgs,
                description="Dump recent Android SMS messages as text.",
            )
            self.dispatcher.register("adb.screenshot_to_local", self.adb.screenshot_to_local, EmptyArgs)
            self.dispatcher.register("adb.qr_generate", self.qr.generate, QRGenerateArgs)
            self.dispatcher.register("adb.qr_terminal", self.qr.print_terminal_qr, QRTerminalArgs)
        self.dispatcher.register("task.schedule", self._schedule_prompt, TaskScheduleArgs)
        self.dispatcher.register("task.list", self._list_jobs, EmptyArgs)
        self.dispatcher.register("task.cancel", self._cancel_job, TaskCancelArgs)
        self.dispatcher.register("goal.run", self._run_goal, GoalRunArgs)
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
        current_session = self.session.current
        session_id = current_session.session_id
        with current_session._lock:
            history = list(current_session.history)

        # Check if we need to trigger background summarization
        if len(history) > self.trimmer.max_raw_turns:
            older = history[: -self.trimmer.max_raw_turns]
            snippet = " ".join(
                f"{turn.get('role', 'user')}: {turn.get('content', '').strip()}"
                for turn in older
                if turn.get("content")
            )
            # Trigger background summarization if snippet changed
            snippet_hash = hashlib.sha256(snippet.encode("utf-8")).hexdigest()
            with self._summary_submit_lock:
                retry_after = self._summary_retry_after.get(session_id, 0.0)
                last_hash = self._last_snippet_hashes.get(session_id)
                older_count = len(older)
                last_trigger_count = self._summary_last_trigger_count.get(session_id, 0)
                has_existing_summary = bool(self.trimmer.summaries.get(session_id, "").strip())
                enough_new_turns = (older_count - last_trigger_count) >= 3 or not has_existing_summary
                if (
                    time.time() >= retry_after
                    and snippet_hash != last_hash
                    and session_id not in self._summary_inflight
                    and enough_new_turns
                ):
                    self._last_snippet_hashes[session_id] = snippet_hash
                    self._summary_last_trigger_count[session_id] = older_count
                    self._summary_inflight.add(session_id)

                    def _job(sn=snippet, sid=session_id):
                        try:
                            self._summarize_history_background(sn, sid)
                        finally:
                            with self._summary_submit_lock:
                                self._summary_inflight.discard(sid)
                                self._summary_jobs_inflight = max(0, self._summary_jobs_inflight - 1)

                    if self._summary_jobs_inflight < self._max_background_summary_jobs:
                        self._summary_jobs_inflight += 1
                        self._summarize_executor.submit(_job)
        
        summary, recent = self.trimmer.trim(
            history,
            session_id=session_id,
            summarizer=lambda snippet: self._summarize_history(snippet, session_id),
        )
        memories = self.memory.search(user_text, session_id=session_id, top_k=DEFAULT_MEMORY_TOP_K)
        world_state = snapshot_environment(include_clipboard=settings.INCLUDE_CLIPBOARD_IN_CONTEXT)

        context_block = {
            "world_state": world_state,
            "relevant_memories": memories,
            "summary_of_older_turns": summary,
            "last_raw_turns": recent,
        }

        context_message = {
            "role": "user",
            "content": "Context payload:\n" + json.dumps(context_block, ensure_ascii=False),
        }

        system_prompt = build_system_prompt(
            self.base_system_prompt,
            dispatcher=self.dispatcher,
            emotion=self.emotion.state,
        )

        # Fix 2.9: Check total token count and trim if needed
        all_messages = [context_message, *recent]
        try:
            total_tokens = estimate_tokens_from_messages([{"role": "system", "content": system_prompt}] + all_messages)
            # If we overflow, drop oldest turns using real per-turn token estimates.
            while total_tokens > MAX_CONTEXT_TOKENS and len(recent) > 1:
                dropped = recent.pop(0)
                total_tokens -= estimate_tokens_from_messages([dropped])
            all_messages = [context_message, *recent]
            # If even context+1 turn overflow, truncate context payload to fit.
            if total_tokens > MAX_CONTEXT_TOKENS:
                base = "Context payload:\n"
                payload = context_message["content"][len(base):]
                while total_tokens > MAX_CONTEXT_TOKENS and len(payload) > 200:
                    payload = payload[: int(len(payload) * 0.85)]
                    context_message["content"] = base + payload
                    all_messages = [context_message, *recent]
                    total_tokens = estimate_tokens_from_messages(
                        [{"role": "system", "content": system_prompt}] + all_messages
                    )
        except Exception:
            pass

        return system_prompt, all_messages, memories

    def _summarize_history(self, text: str, session_id: str) -> str:
        """Summarize conversation history. Uses cached summary if available."""
        if not text.strip():
            return ""

        stable_hash = hashlib.sha256(f"{session_id}:{text}".encode("utf-8")).hexdigest()
        with self._summary_cache_lock:
            if stable_hash in self._summary_cache:
                self._summary_cache.move_to_end(stable_hash)  # Keep LRU fresh
                return self._summary_cache[stable_hash]

        # No cached summary yet; background worker will populate it.
        return ""
    
    def _summarize_history_background(self, text: str, session_id: str) -> None:
        """Summarize history in background thread and update cache."""
        if not text.strip():
            return
            
        try:
            system = "Summarize the conversation history into a concise paragraph for future context."
            summary = self.engine.ask(prompt=text, system=system, history=[])
            self._track_usage(system, [], "[history_summary]", summary)
            if not str(summary).strip():
                return
            # Fix 3.2 & 11: Lock around LRU ordered dict cache 
            with self._summary_cache_lock:
                stable_hash = hashlib.sha256(f"{session_id}:{text}".encode("utf-8")).hexdigest()
                self._summary_cache[stable_hash] = summary
                if len(self._summary_cache) > 50:
                    self._summary_cache.popitem(last=False)
            with self.trimmer._lock:
                self.trimmer.summaries[session_id] = summary
            with self._summary_submit_lock:
                # Cool down re-summarization churn after a successful summary.
                self._summary_retry_after[session_id] = time.time() + 30.0
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning("Summarizer thread failed unconditionally: %s", e)
            with self._summary_submit_lock:
                self._summary_retry_after[session_id] = time.time() + 60.0
                self._last_snippet_hashes.pop(session_id, None)

    def _apply_text_commands(self, user_text: str) -> str | None:
        """Handle built-in text shortcuts without calling the LLM.

        Minor fix: session names and agent identity strings are now read from
        config.constants so a project rename requires only one file change.
        """
        text = user_text.strip().lower()
        
        def cmd(c: str) -> bool:
            return text.startswith(f"/{c}")
            
        if cmd("approve_goal"):
            parts = user_text.strip().split()
            candidate_id = parts[1] if len(parts) > 1 else None
            with self._goal_lock:
                for goal in self._goals:
                    if candidate_id and goal["id"] == candidate_id and goal["status"] == "awaiting_confirmation":
                        goal["status"] = "approved_for_step"
                        self._persist_goals()
                        return f"Goal {candidate_id} approved for next step."
                    elif not candidate_id and goal["status"] == "awaiting_confirmation":
                        goal["status"] = "approved_for_step"
                        self._persist_goals()
                        return f"Goal {goal['id']} approved for next step."
            return "No matching goal awaiting confirmation."

        agent = AGENT_NAME.lower()
        if text in {"switch to work mode", "work mode", "switch to work"}:
            state = self.switch_session(DEFAULT_SESSION_WORK)
            return f"Switched to {state.name} ({state.session_id})."
        if text in {"switch to personal mode", "personal mode", "switch to personal"}:
            state = self.switch_session(DEFAULT_SESSION_PERSONAL)
            return f"Switched to {state.name} ({state.session_id})."
        if text in {"reset context", "clear context"}:
            self.reset_context()
            return "Context reset for this session. Memories are still saved."
        if text in {f"{agent} stop", "emergency stop", "stop now"}:
            guardrails.emergency_stop()
            return "Emergency stop is active. Tool execution is now blocked."
        if text in {f"{agent} resume", "clear emergency stop", "resume tools"}:
            guardrails.clear_emergency_stop()
            return "Emergency stop cleared. Tool execution is enabled."
        if text in {"safety status", "emergency status"}:
            state = "active" if guardrails.is_emergency_stopped() else "inactive"
            return f"Emergency stop is {state}."
        if text in {"mute", f"{agent} mute", "mute notifications"}:
            self.set_muted(True)
            return "Muted. Proactive alerts and autonomy notifications are silenced."
        if text in {"unmute", f"{agent} unmute", "unmute notifications"}:
            self.set_muted(False)
            return "Unmuted. Proactive alerts and autonomy notifications are active."
        if text in {"toggle mute", "mute toggle"}:
            now_muted = self.toggle_mute()
            return "Muted." if now_muted else "Unmuted."
        if re.match(r"^switch session\s+.+$", text):
            # Retain original casing by slicing from user_text
            name = user_text.strip()[len("switch session "):].strip()
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
        command_response = self._apply_text_commands(user_text)
        if command_response:
            yield command_response
            return

        today = date.today()
        hard_cap_active = False
        with self._usage_lock:
            if self._hard_cap_hit_date != today:
                self._hard_cap_hit = False
                self._hard_cap_hit_date = None
            hard_cap_active = self._hard_cap_hit
        if hard_cap_active:
            yield f"Daily token hard cap of {settings.DAILY_TOKEN_HARD_CAP} reached. Further calls blocked."
            return

        self.emotion.update_from_signal(user_text)
        self.memory.set_online(NetworkState.is_online())
        if self.memory.online:
            self._schedule_sync_all_pending()

        if needs_clarification(user_text):
            question = clarifying_question(user_text)
            self.session.add_turn("user", user_text)
            self.session.add_turn("assistant", question)
            yield question
            return

        system_prompt, history, _ = self._context_messages(user_text)

        output_chunks: list[str] = []
        stream = self.engine.ask_stream(prompt=user_text, system=system_prompt, history=history)
        user_added = False
        committed = False
        usage_tracked = False
        assistant_text = ""

        try:
            try:
                first_token = next(stream)
                self.session.add_turn("user", user_text)
                user_added = True
                output_chunks.append(first_token)
                yield first_token
                for token in stream:
                    output_chunks.append(token)
                    yield token
            except StopIteration:
                if not user_added:
                    self.session.add_turn("user", user_text)
                    user_added = True
            except RuntimeError as exc:
                # PEP 479: inner StopIteration may surface as RuntimeError.
                if "StopIteration" in str(exc):
                    if not user_added:
                        self.session.add_turn("user", user_text)
                        user_added = True
                else:
                    raise

            assistant_text = "".join(output_chunks).strip()
            tool_call = self.dispatcher.try_parse_tool_call(assistant_text) if allow_tools else None
            if tool_call:
                result = self.dispatcher.execute(
                    tool_call,
                    confirm_callback=self._interactive_confirm,
                    dry_run=dry_run_tools,
                )
                tool_result_text = f"[tool_result] {json.dumps(result, ensure_ascii=False)}"
                if output_chunks:
                    yield "\n"
                yield tool_result_text
                assistant_text = tool_result_text

            self.session.add_turn("assistant", assistant_text)
            committed = True
            self._track_usage(system_prompt, history, user_text, assistant_text, day_anchor=today)
            usage_tracked = True
            self._commit_memory_async(user_text, assistant_text)
        except Exception as exc:
            yield f"[ERROR] Generation failed: {exc}"
        finally:
            # If caller abandons this generator mid-stream, persist partial output.
            if not committed and (user_added or output_chunks):
                partial = assistant_text or "".join(output_chunks).strip()
                if not partial:
                    return
                if not user_added:
                    self.session.add_turn("user", user_text)
                    user_added = True
                try:
                    if not usage_tracked:
                        self._track_usage(system_prompt, history, user_text, partial, day_anchor=today)
                except Exception:
                    pass
                if not assistant_text:
                    self.session.add_turn("assistant", partial)
                self._commit_memory_async(user_text, partial)

    def _commit_memory_async(self, user_text: str, assistant_text: str) -> None:
        if self._shutting_down.is_set():
            return
        session_id = self.session.current.session_id

        def _job() -> None:
            try:
                self.memory.add(
                    text=f"User: {user_text}\nAssistant: {assistant_text}",
                    session_id=session_id,
                    metadata={"source": "conversation"},
                )
                self.memory.sync_pending(session_id)
            finally:
                with self._memory_submit_lock:
                    self._memory_jobs_inflight = max(0, self._memory_jobs_inflight - 1)

        try:
            with self._memory_submit_lock:
                if self._memory_jobs_inflight >= self._max_background_memory_jobs:
                    return
                self._memory_jobs_inflight += 1
            self._memory_executor.submit(_job)
        except Exception:
            # Fallback to sync path if executor is unavailable.
            with self._memory_submit_lock:
                self._memory_jobs_inflight = max(0, self._memory_jobs_inflight - 1)
            _job()

    def _adb_send_sms(self, phone_number: str, body: str) -> str:
        """Send SMS via ADB client."""
        if not self.adb:
            return "Error: ADB not available"
        return self.adb.send_sms(phone_number, body)

    def _track_usage(
        self,
        system_prompt: str,
        history: list[dict],
        user_text: str,
        assistant_text: str,
        *,
        day_anchor: date | None = None,
    ) -> None:
        input_tokens = estimate_tokens(system_prompt) + estimate_tokens(user_text)
        input_tokens += sum(estimate_tokens(str(m.get("content", ""))) for m in history)
        output_tokens = estimate_tokens(assistant_text)

        today = day_anchor or date.today()
        with self._usage_lock:
            session_id = self.session.current.session_id
            provider = self.engine.last_provider
            self.usage.add(provider, input_tokens, output_tokens, session_id=session_id, when=today)
            total = self.usage.total_tokens_today(session_id=session_id)
            if self._hard_cap_hit_date != today:
                self._hard_cap_hit = False
                self._hard_cap_hit_date = None
            if self._hard_cap_warning_day != today:
                self._hard_cap_warning_day = None
            hardcap = settings.DAILY_TOKEN_HARD_CAP
            warning_pct = max(0, min(100, int(settings.DAILY_TOKEN_HARD_CAP_WARNING_PCT)))
            if hardcap > 0 and warning_pct > 0 and self._hard_cap_warning_day != today:
                threshold = int(hardcap * (warning_pct / 100.0))
                if total >= threshold:
                    self._hard_cap_warning_day = today
                    warn_msg = (
                        f"[usage] Warning: daily token usage {total} reached {warning_pct}% "
                        f"of hard cap {hardcap}."
                    )
                    print(warn_msg)
                    try:
                        self._notify_telegram(warn_msg)
                    except Exception:
                        pass
            if hardcap > 0 and total >= hardcap and not self._hard_cap_hit:
                self._hard_cap_hit = True
                self._hard_cap_hit_date = today
                msg = f"[usage] HARD CAP REACHED: daily token usage {total} >= hard cap {hardcap}. Further LLM calls are blocked for today."
                print(msg)
                try:
                    self._notify_telegram(msg)
                except Exception:
                    pass
            # ↓ THIS BLOCK MUST ALSO BE INSIDE THE WITH:
            if self._usage_alerted_day != today:
                if total >= settings.DAILY_TOKEN_ALERT_THRESHOLD:
                    print(f"\n[usage] Warning: daily token usage {total} exceeded threshold {settings.DAILY_TOKEN_ALERT_THRESHOLD}.")
                    self._usage_alerted_day = today

    def _schedule_sync_all_pending(self) -> None:
        now = time.monotonic()
        with self._sync_all_lock:
            if self._sync_all_inflight:
                return
            if now - self._last_sync_all_pending < 15.0:
                return
            self._sync_all_inflight = True
            self._last_sync_all_pending = now

        def _job() -> None:
            try:
                self.memory.sync_all_pending()
            except Exception:
                pass
            finally:
                with self._sync_all_lock:
                    self._sync_all_inflight = False

        try:
            self._sync_executor.submit(_job)
        except Exception:
            with self._sync_all_lock:
                self._sync_all_inflight = False

    def _interactive_confirm(self, prompt: str) -> bool:
        try:
            import sys
            if not sys.stdin or not sys.stdin.isatty():
                self._notify_telegram(f"High-risk confirmation required but no interactive stdin is available.\n{prompt}")
                return False
            answer = input(prompt).strip().lower()
            return answer in {"y", "yes", "confirm"}
        except Exception:
            return False


def main() -> int:
    setup_logger()
    startup_delay = max(0.0, float(getattr(settings, "NOVA_STARTUP_DELAY_SECONDS", 0.0)))
    if startup_delay > 0.0:
        print(f"[startup] Delaying boot by {startup_delay:.1f}s (NOVA_STARTUP_DELAY_SECONDS)")
        time.sleep(startup_delay)
    try:
        app = NOVAApp()
    except SettingsError as exc:
        print(str(exc))
        return 1

    # fix 7.8: graceful shutdown on SIGTERM and SIGINT
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


# Backward-compatibility alias so any code/tests referencing JarvisApp still work.
# JarvisApp is NOVAApp — same class, not a subclass.
JarvisApp = NOVAApp
