"""NOVA entry point."""

from __future__ import annotations

import json
import signal
import time
import hashlib
import uuid
import ipaddress
import os
import socket
from pathlib import Path
import re
import threading
import sys
import shutil
from collections import deque, OrderedDict
from typing import Any, Generator
from datetime import date, datetime
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
from interfaces.key_manager import EncryptedKeyStore
from interfaces.model_manager import list_ollama_models
from mcp.master_api import MasterAPI
from mcp.master_mcp import BUILTIN_SERVICES, MasterMCP
from rag.doc_store import DocumentStore
from safety.guardrails import guardrails
from safety.virus_scanner import VirusScanner
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
from web.scraper import scrape_text, scrape_js, scrape_visual
from web.search import search
import control.win32_api as win32_api
# Feature imports ──────────────────────────────────────────────────────────────
from config.pc_scanner import load as _load_pc_profile
from config.capability_map import build_capability_summary
from control.window_manager import WindowManager
from control.macos_permissions import check_permissions as _check_macos_permissions
from interfaces.onboarding import run_onboarding
from core.plugin_generator import PluginGenerator
# ── Proactive Intelligence layer ──────────────────────────────────────────────
from utils.behavior_model import BehaviorModel
from utils.commitment_extractor import extract_commitments, iter_commitments_from_history
from utils.tool_profiler import ToolProfiler
from utils.presence_manager import PresenceManager
from utils.insight_extractor import InsightExtractor
from core.memory.intent_graph import IntentGraph
from core.context.fs_watcher import NOVAFSWatcher
from core.llm.network_context import NetworkContextDetector
from core.goals.template_library import GoalTemplateLibrary
from core.goals.proactive_goal_engine import ProactiveGoalEngine
from core.think.prompt_evolver import PromptEvolver
from core.think.self_evaluator import SelfEvaluator
from core.think.nudge_engine import NudgeEngine
from core.a2a.peer_registry import PeerRegistry
from core.a2a.shared_memory_bus import SharedMemoryBus
from core.a2a.role_manager import assign_role
from core.a2a.conflict_resolver import ConflictResolver
from tasks.maintenance import MaintenanceOrchestrator
from tasks.missions import MissionManager
from tasks.pattern_shortcuts import PatternShortcutCompiler
from tasks.automation_factory import AutomationFactory
from voice.ambient_listener import AmbientListener, AmbientEvent
from vision.gemini_vision import analyze_image as gemini_analyze_image


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


class SafetyScanFileArgs(BaseModel):
    path: str


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


class WindowListArgs(BaseModel):
    pass


class WindowFocusArgs(BaseModel):
    title: str


class WindowResizeWMArgs(BaseModel):
    title: str
    width: int
    height: int


class WindowCloseArgs(BaseModel):
    title: str


class PluginGenerateArgs(BaseModel):
    description: str = Field(..., min_length=5, max_length=1000)


class ScrapeJsArgs(BaseModel):
    url: str


class ScrapeVisualArgs(BaseModel):
    url: str


class EmptyArgs(BaseModel):
    pass


class TaskScheduleArgs(BaseModel):
    schedule_text: str
    prompt: str
    job_id: str | None = None


class TaskCancelArgs(BaseModel):
    job_id: str


class MissionAddArgs(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    schedule: str = Field(..., min_length=3, max_length=120)
    goal: str = Field(..., min_length=3, max_length=2000)
    enabled: bool = True


class MissionToggleArgs(BaseModel):
    name: str


class MissionRunArgs(BaseModel):
    name: str


class ShortcutRunArgs(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    dry_run: bool = False


class LearnSkillArgs(BaseModel):
    skill_name: str = Field(..., min_length=2, max_length=120)


class ApiAutodiscoveryArgs(BaseModel):
    api_name: str = Field(..., min_length=2, max_length=200)


class GameBotArgs(BaseModel):
    game_name: str = Field(..., min_length=2, max_length=120)


class LearnAppArgs(BaseModel):
    app_name: str = Field(..., min_length=2, max_length=120)


class LiveFeedArgs(BaseModel):
    topic: str = Field(..., min_length=2, max_length=160)
    interval_minutes: int = Field(default=5, ge=1, le=120)


class BatchApiArgs(BaseModel):
    api_names: list[str] = Field(default_factory=list)


class FailureRecoveryArgs(BaseModel):
    step_key: str = Field(..., min_length=1, max_length=200)
    screenshot_path: str = ""


class ContextModeArgs(BaseModel):
    context_label: str = Field(..., min_length=2, max_length=120)


class A2ASendArgs(BaseModel):
    to_agent: str
    msg_type: str = "status_update"
    payload: dict = Field(default_factory=dict)


class A2AClaimArgs(BaseModel):
    path: str


class A2AInboxArgs(BaseModel):
    limit: int = Field(default=50, ge=1, le=200)


class A2ADelegateArgs(BaseModel):
    to_agent: str
    tool_name: str
    args: dict = Field(default_factory=dict)
    service: str | None = None


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
        self._self_eval_executor = ThreadPoolExecutor(max_workers=1)
        self.goal_runner = None
        self.autonomy_runner = None
        self._tts_queue = queue.Queue()
        self._tts_thread = threading.Thread(target=self._tts_worker, daemon=True)

        # Optional BYOK keystore bootstrap.
        keystore_password = os.getenv("NOVA_KEYSTORE_PASSWORD", "").strip()
        if keystore_password:
            try:
                store = EncryptedKeyStore()
                loaded = store.load(keystore_password)
                if loaded.get("openai"):
                    settings.OPENAI_API_KEYS = list(loaded["openai"])
                if loaded.get("gemini"):
                    settings.GEMINI_API_KEYS = list(loaded["gemini"])
                if loaded.get("mem0"):
                    settings.MEM0_API_KEY = str(loaded["mem0"][0])
                if loaded.get("telegram"):
                    settings.TELEGRAM_BOT_TOKEN = str(loaded["telegram"][0])
                if loaded.get("porcupine"):
                    settings.PORCUPINE_ACCESS_KEY = str(loaded["porcupine"][0])
                if loaded.get("virustotal"):
                    settings.VIRUSTOTAL_API_KEY = str(loaded["virustotal"][0])
            except Exception:
                pass

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
        self._theme_lock_name = ""
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
        self._session_privacy_overrides: dict[str, str] = {}

        # Bug 1 fix: if the persisted usage was from a previous day, don't carry
        # _hard_cap_hit forward — the user would be silently blocked all of day 2.
        total_today = self.usage.total_tokens_today(session_id=None)
        _today = date.today()
        if settings.DAILY_TOKEN_HARD_CAP > 0 and total_today >= settings.DAILY_TOKEN_HARD_CAP:
            self._hard_cap_hit = True
            self._hard_cap_hit_date = _today
        else:
            # Ensure any stale flag from yesterday is cleared at startup.
            self._hard_cap_hit = False
            self._hard_cap_hit_date = None

        # ── Feature 10: first-run onboarding ──────────────────────────────────
        try:
            run_onboarding(force=False)
        except Exception as _exc:
            import logging
            logging.getLogger(__name__).debug("Onboarding skipped: %s", _exc)

        # ── Feature 16: macOS permission check ────────────────────────────────
        try:
            _check_macos_permissions(warn_only=True)
        except Exception:
            pass

        # ── Feature 4+7: load PC profile and build capability summary ─────────
        try:
            _profile = _load_pc_profile()
            self._capability_summary: str = build_capability_summary(_profile)
        except Exception:
            self._capability_summary = ""

        # ── Feature 14: window manager ────────────────────────────────────────
        try:
            self._window_manager = WindowManager()
        except Exception:
            self._window_manager = None
        
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
        self._session_context_epoch: dict[str, int] = {}

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
        self._virus_scanner = VirusScanner(api_key=settings.VIRUSTOTAL_API_KEY)
        self.docs = DocumentStore()
        self._browser: Browser | None = None
        self._browser_needs_reset = False
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
                    if goal.get("status") == "running":
                        goal["status"] = "pending"
                    elif goal.get("status") == "planning":
                        goal["status"] = "failed"
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
            on_screen_state=lambda active_app, scene_type: (
                self._behavior_model.record_screen_state(active_app, scene_type),
                self._nudge_engine.update_context(task_key=f"{active_app}:{scene_type}"),
            ),
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
        self._self_evaluator = SelfEvaluator(
            llm_ask_fn=lambda prompt, system: self.engine.ask(prompt=prompt, system=system, history=[]),
        )
        self._nudge_engine = NudgeEngine(export_callback=lambda: self.export_session("md"))
        self._ambient_whisper = None
        self._ambient_whisper_lock = threading.Lock()
        self._ambient_listener = AmbientListener(
            keywords=list(getattr(settings, "AMBIENT_KEYWORDS", [])),
            on_event=self._handle_ambient_event,
            transcribe_fn=self._ambient_transcribe,
        )
        self._a2a_enabled = bool(getattr(settings, "A2A_ENABLED", False))
        self._a2a_agent_name = str(getattr(settings, "A2A_AGENT_NAME", "nova")).strip() or "nova"
        self._peer_registry = PeerRegistry()
        self._shared_bus = SharedMemoryBus(path=getattr(settings, "A2A_SHARED_BUS_PATH", ".jarvis/shared_bus.jsonl"))
        self._conflict_resolver = ConflictResolver()
        self._mission_manager = MissionManager(
            scheduler=self.scheduler,
            enqueue_goal_fn=lambda goal_text: self._add_goal(goal_text, max_steps=settings.AUTONOMY_MAX_STEPS),
        )
        self._shortcut_compiler = PatternShortcutCompiler()
        self._automation_factory = AutomationFactory(
            plugin_generate_fn=lambda prompt: self._plugin_generator.generate_and_propose(prompt)
            if hasattr(self, "_plugin_generator")
            else {"status": "error", "reason": "plugin_generator_unavailable"},
            schedule_every_fn=lambda name, schedule, goal: self._mission_add(name, schedule, goal, True),
            notify_tts_fn=self._notify_tts,
            vision_analyze_fn=gemini_analyze_image,
            record_event_fn=self.record_event,
        )
        self._ensure_default_missions()
        self.base_system_prompt = DEFAULT_SYSTEM_PROMPT
        self._register_builtin_tools()
        if self._a2a_enabled:
            try:
                self._a2a_register_presence()
                self._a2a_send(
                    to_agent="broadcast",
                    msg_type="status_update",
                    payload={"status": "online", "session": self.session.current.name},
                )
            except Exception:
                pass
        
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
        self._network_online_cache: bool | None = None
        self._network_online_cache_at = 0.0
        self._network_online_ttl_seconds = 30.0
        self._network_online_lock = threading.Lock()
        self._network_online_refresh_inflight = False

        # ── Proactive Intelligence — Tier 1-5 components ──────────────────────
        self._behavior_model   = BehaviorModel(privacy_mode=False)
        self._intent_graph     = IntentGraph(privacy_mode=False)
        self._tool_profiler    = ToolProfiler()
        try:
            from utils.tool_profiler import set_tool_profiler_instance
            set_tool_profiler_instance(self._tool_profiler)
        except Exception:
            pass
        self._template_library = GoalTemplateLibrary()
        self._prefetch_cache: dict[str, list] = {}      # Tier 3 speculative RAG
        self._queued_alerts: deque = deque(maxlen=20)   # Tier 3 attention-aware queue
        self._error_detections_this_hour: int = 0       # Tier 2 emotion predictor input
        self._error_counter_hour: tuple[int, int] | None = None
        self._last_process_set: set[str] = set()        # Tier 1 process monitor
        self._session_start_time = time.monotonic()     # Tier 2 session length tracking

        self._presence_manager = PresenceManager(
            telegram_fn=self._notify_telegram,
            mcp_call_fn=lambda service, tool_name, args: self.master_mcp.call_tool(service, tool_name, **(args or {})),
            connected_services_fn=lambda: self.master_mcp.list_services(),
            record_event_fn=self.record_event,
            muted_fn=lambda: self._muted,
        )

        def _on_network_change(old_ctx: str, new_ctx: str) -> None:
            import logging
            logging.getLogger(__name__).info("[proactive] Network context: %s → %s", old_ctx, new_ctx)
            target = "nova_work" if new_ctx == "work" else "nova_personal"
            try:
                self.switch_session(target)
                self._notify_telegram(f"🌐 Network context changed to *{new_ctx}* — switched to {target} session.")
            except Exception:
                pass

        self._network_ctx_detector = NetworkContextDetector(on_change=_on_network_change)

        def _on_doc_changed(filepath: str) -> None:
            try:
                self.docs.update(filepath)
            except Exception:
                pass

        def _on_git_commit(msg: str) -> None:
            try:
                sid = self.session.current.session_id
                self.memory.add(f"Git commit: {msg}", sid, {"source": "git"})
            except Exception:
                pass

        watched_paths = list(getattr(self.docs, "_doc_meta", {}).keys())
        self._fs_watcher = NOVAFSWatcher(
            watched_paths=watched_paths,
            on_file_changed=_on_doc_changed,
            on_git_commit=_on_git_commit,
        )

        self._insight_extractor = InsightExtractor(
            llm_ask_fn=lambda p, s: self.engine.ask(prompt=p, system=s, history=[]),
            memory_get_all_fn=lambda sid: self.memory.get_all(sid) if hasattr(self.memory, 'get_all') else [],
            memory_add_fn=lambda text, sid, meta: self.memory.add(text, sid, meta),
            notify_fn=self._notify_telegram,
            estimate_tokens_fn=lambda t: estimate_tokens(t),
            session_list_fn=lambda: list(self.session._sessions.keys()) if hasattr(self.session, '_sessions') else [self.session.current.session_id],
        )

        def _get_baseline_success() -> float:
            goals = self._goals
            completed = sum(1 for g in goals if g.get("status") == "completed")
            total = max(1, len(goals))
            return completed / total

        self._prompt_evolver = PromptEvolver(
            llm_ask_fn=lambda p, s: self.engine.ask(prompt=p, system=s, history=[]),
            notify_fn=self._notify_telegram,
            get_baseline_success_rate_fn=_get_baseline_success,
        )
        self._monday_insight_checked_on: date | None = None
        self._last_behavior_goal_proposal_at = 0.0

        def _propose_proactive_goal(goal_dict: dict) -> None:
            """Add a proposed goal to the goals list and notify."""
            with self._goal_lock:
                if len(self._goals) >= self._max_pending_goals:
                    return
                self._goals.append(goal_dict)
                self._persist_goals()
            desc = goal_dict.get("goal", "")[:80]
            gid = goal_dict.get("id", "")
            self._notify_telegram(
                f"💡 *Proactive goal queued:* {desc}\n"
                f"It will auto-start in 5 min unless cancelled: `/cancel_goal {gid}`"
            )

        self._proactive_engine = ProactiveGoalEngine(
            propose_fn=_propose_proactive_goal,
            risk_check_fn=lambda tool, args: guardrails.check(__import__("core.tools.dispatcher", fromlist=["ToolCall"]).ToolCall(tool=tool, args=args)),
            behavior_model=self._behavior_model,
            intent_graph=self._intent_graph,
            template_library=self._template_library,
            autonomy_enabled=settings.AUTONOMY_ENABLED,
        )

        self._maintenance = MaintenanceOrchestrator(
            notify_fn=self._notify_telegram,
            backup_fn=None,   # wired after scheduler starts
            memory_sync_fn=lambda: self.memory.sync_pending(self.session.current.session_id),
            health_check_fn=lambda: self.health.status_table(),
        )
        # ── end proactive intelligence init ─────────────────────────────────────
        self._apply_privacy_mode_for_session(self.session.current.session_id)

        if settings.PLUGINS_ENABLED:
            try:
                load_plugins(self.dispatcher)
            except Exception as exc:
                import logging
                logging.getLogger(__name__).warning("Plugin loader failed: %s", exc)
        try:
            self.scheduler.start()
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("Scheduler startup failed: %s", exc)
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
            if bool(getattr(settings, "SMART_HOME_DISCOVER_ON_BOOT", True)):
                self._home_discover()
        except Exception:
            pass
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
        # Missing feature fix: schedule daily ChromaDB backup to prevent data loss on corruption
        try:
            if self.scheduler.scheduler.running:
                from core.memory.backup import schedule_daily_backup, _backup_chromadb
                schedule_daily_backup(self.scheduler)
                if getattr(self, "_maintenance", None) is not None:
                    self._maintenance._backup = lambda: _backup_chromadb()
            else:
                import logging
                logging.getLogger(__name__).warning("Skipping backup registration because scheduler is not running.")
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("Failed to schedule ChromaDB backup: %s", exc)
        # Start proactive systems after scheduler is ready
        try:
            self._network_ctx_detector.start()
            self._fs_watcher.start()
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("Proactive system startup failed: %s", exc)
        # Start TTS worker after core subsystems are initialized.
        self._tts_thread.start()

    def last_provider_label(self) -> str:
        return self.engine.last_provider

    @property
    def emotion_state(self) -> str:
        return self.emotion.state

    @staticmethod
    def _normalize_privacy_mode(mode: str) -> str:
        cleaned = (mode or "").strip().lower()
        if cleaned in {"local_only", "balanced", "full_cloud"}:
            return cleaned
        return "full_cloud"

    def _get_session_privacy_mode(self, session_id: str | None = None) -> str:
        sid = session_id or self.session.current.session_id
        override = self._session_privacy_overrides.get(sid)
        if override:
            return self._normalize_privacy_mode(override)
        return self._normalize_privacy_mode(getattr(settings, "PRIVACY_MODE", "full_cloud"))

    def _apply_privacy_mode_for_session(self, session_id: str | None = None) -> str:
        mode = self._get_session_privacy_mode(session_id=session_id)
        remote_memory_ok = mode == "full_cloud"
        try:
            self.memory.set_remote_sync_enabled(remote_memory_ok)
        except Exception:
            pass
        try:
            # In local-only mode, behavioral features avoid richer text capture.
            local_only = mode == "local_only"
            self._behavior_model.privacy_mode = local_only
            self._intent_graph.privacy_mode = local_only
        except Exception:
            pass
        return mode

    def _set_session_privacy_mode(self, mode: str, session_id: str | None = None) -> str:
        normalized = self._normalize_privacy_mode(mode)
        sid = session_id or self.session.current.session_id
        self._session_privacy_overrides[sid] = normalized
        self._apply_privacy_mode_for_session(session_id=sid)
        return normalized

    def set_theme_lock(self, theme_name: str) -> str:
        cleaned = (theme_name or "").strip().lower()
        if cleaned in {"", "auto", "none", "default_auto"}:
            self._theme_lock_name = ""
            return "auto"
        self._theme_lock_name = cleaned
        return cleaned

    def get_theme_lock(self) -> str:
        return self._theme_lock_name or "auto"

    def switch_session(self, name: str):
        previous_session_id = self.session.current.session_id
        state = self.session.switch(name)
        # Clear per-session summary state on switch to avoid stale bleed-through.
        self._clear_session_context_state(previous_session_id, clear_summary=False)
        self._clear_session_context_state(state.session_id, clear_summary=True)
        # Cancel any running goal on this session before closing resources
        with self._goal_lock:
            for g in self._goals:
                if g.get("status") in {"planning", "pending", "running", "approved_for_step", "awaiting_confirmation"}:
                    g["status"] = "cancelled"
                    if "last_result" not in g:
                        g["last_result"] = {"status": "cancelled", "reason": "session_switched"}
        # Session isolation: reset stateful tool clients on session switch.
        if self._browser_lock.acquire(timeout=1.0):
            try:
                if self._browser is not None:
                    self._browser.close()
            except Exception:
                pass
            finally:
                self._browser = None
                self._browser_needs_reset = False
                self._browser_lock.release()
        else:
            import logging
            logging.getLogger(__name__).warning("Browser lock timeout during session switch; force-dropping browser handle.")
            self._browser = None
            self._browser_needs_reset = True
        self._mouse_keyboard = None
        # Bug 7 fix: reset omniparser client so it is not shared across sessions.
        self._omniparser_client = None
        if getattr(self, "adb", None):
            try:
                self.adb.device = None
            except Exception:
                pass
        self._apply_privacy_mode_for_session(state.session_id)
        if getattr(self, "_a2a_enabled", False):
            try:
                self._a2a_register_presence()
            except Exception:
                pass
        return state

    def _clear_session_context_state(self, session_id: str, *, clear_summary: bool) -> None:
        with self._summary_submit_lock:
            self._summary_last_trigger_count.pop(session_id, None)
            self._summary_retry_after.pop(session_id, None)
            self._last_snippet_hashes.pop(session_id, None)
            self._summary_inflight.discard(session_id)
            self._session_context_epoch[session_id] = self._session_context_epoch.get(session_id, 0) + 1
        with self.trimmer._lock:
            if clear_summary:
                self.trimmer.summaries.pop(session_id, None)
            self.trimmer._last_summarized_count.pop(session_id, None)

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
        except Exception as exc:
            import logging
            logging.getLogger(__name__).error("Session backup failed before reset: %s", exc)
        self.session.reset_context()
        # fix 1.6: clear stale summary and invalidate in-flight summarizer writes.
        self._clear_session_context_state(session_id, clear_summary=True)

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
        nonce = uuid.uuid4().hex[:6]
        base_name = re.sub(r"[^a-zA-Z0-9_-]+", "_", session.name).strip("_") or "session"
        safe_name = f"{base_name}_{session.session_id[:8]}"
        if history is None:
            with session._lock:
                payload = list(session.history)
        else:
            payload = list(history)
        if fmt.lower() == "json":
            path = f"exports/{safe_name}_{timestamp}_{nonce}.json"
            return export_json(payload, path)
        path = f"exports/{safe_name}_{timestamp}_{nonce}.md"
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
                "missions": self._mission_manager.list_missions(),
                "tailscale_ip": tailscale_ip_v4(),
                "tailscale_status": tailscale_status(),
                "mcp_connected_services": self.master_mcp.list_services(),
                "mcp_registered_keys": self.master_api.list_services(),
                "muted": self._muted,
                "privacy_mode": self._get_session_privacy_mode(),
                "theme_lock": self.get_theme_lock(),
                "a2a_enabled": self._a2a_enabled,
                "a2a_role": self._a2a_role(),
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
        if self._browser_needs_reset and self._browser is not None:
            try:
                self._browser.close()
            except Exception:
                pass
            self._browser = None
            self._browser_needs_reset = False
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
        # ── Tier 5: Try template before calling LLM ──────────────────────────
        if hasattr(self, '_template_library') and self._template_library:
            available = set(self.dispatcher.registry.keys()) if hasattr(self.dispatcher, 'registry') else set()
            tmpl = self._template_library.find_matching_template(goal, available_tools=available)
            if tmpl:
                import logging
                logging.getLogger(__name__).info("[plan_goal] using template '%s' (skipping LLM)", tmpl.name)
                return {
                    "steps": list(tmpl.steps),
                    "goal": goal,
                    "from_template": True,
                    "template_name": tmpl.name,
                }

        # ── Tier 5: Inject tool reliability warning from profiler ─────────────
        reliability_warning = ""
        if hasattr(self, '_tool_profiler') and self._tool_profiler:
            reliability_warning = self._tool_profiler.get_planner_warning()

        planner_prompt = (
            "You are a planning assistant. Break the user's goal into a short sequence of tool calls.\n"
            "Return ONLY valid JSON. Prefer this format:\n"
            '[{"tool": "<tool_name>", "args": {...}}, ...]\n'
            "No prose, no markdown. Keep it concise."
        )
        if reliability_warning:
            planner_prompt += f"\n\nNOTE: {reliability_warning}"

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
        usage_system_prompt = system_prompt
        for attempt in range(3):
            if self._is_hard_cap_active_today(date.today()):
                return {"goal": goal, "status": "failed", "reason": "daily_hard_cap_reached"}
            raw = self.engine.ask(prompt=f"Goal: {goal}", system=system_prompt, history=[])
            self._track_usage(usage_system_prompt, [], f"[goal_plan] {goal}", raw)
            if self._is_hard_cap_active_today(date.today()):
                return {"goal": goal, "status": "failed", "reason": "daily_hard_cap_reached"}
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
            "session_id": self.session.current.session_id,
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
            self._goal_plan_jobs_inflight += 1
        inflight_released = {"value": False}

        def _release_plan_slot() -> None:
            with self._goal_plan_submit_lock:
                if inflight_released["value"]:
                    return
                inflight_released["value"] = True
                self._goal_plan_jobs_inflight = max(0, self._goal_plan_jobs_inflight - 1)

        def background_plan():
            try:
                if self._shutting_down.is_set():
                    return
                plan = self._plan_goal(goal, max_steps=min(max_steps, 30))
            except Exception as exc:
                plan = {"status": "failed", "reason": f"planning_exception:{exc}"}
            try:
                if self._shutting_down.is_set():
                    return
                with self._goal_lock:
                    for item in self._goals:
                        if item.get("id") == goal_id:
                            if item.get("status") == "cancelled":
                                break
                            if plan.get("status") == "ok":
                                item["steps"] = plan["steps"]
                                item["status"] = "pending"
                            else:
                                item["status"] = "failed"
                                item["last_result"] = plan
                            self._persist_goals()
                            break
            finally:
                _release_plan_slot()

        try:
            future = self._goal_plan_executor.submit(background_plan)
        except Exception as exc:
            _release_plan_slot()
            with self._goal_lock:
                for item in self._goals:
                    if item.get("id") == goal_id and item.get("status") == "planning":
                        item["status"] = "failed"
                        item["last_result"] = {"status": "failed", "reason": f"planning_submit_exception:{exc}"}
                        self._persist_goals()
                        break
            return {"status": "error", "reason": f"planning_submit_exception:{exc}", "id": goal_id}
        def _on_done(fut):
            if fut.cancelled():
                _release_plan_slot()
                return
            if self._shutting_down.is_set():
                return
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
        target = Path(raw).expanduser().resolve(strict=False)
        protected_prefixes = [Path("/etc"), Path("/proc"), Path("/sys"), Path("/dev")]
        if any(str(target).startswith(str(p)) for p in protected_prefixes):
            return {"status": "error", "reason": "path_not_allowed"}
        allowed_roots = [
            Path(os.getenv("NOVA_DOCS_ROOT", str(Path.cwd()))).expanduser().resolve(),
            Path.home().resolve(),
        ]
        inside_allowed = False
        for root in allowed_roots:
            try:
                target.relative_to(root)
                inside_allowed = True
                break
            except Exception:
                continue
        if not inside_allowed:
            return {
                "status": "error",
                "reason": "path_outside_allowed_roots",
                "path": str(target),
                "allowed_roots": [str(root) for root in allowed_roots],
            }
        try:
            scan = self._virus_scanner.scan_file(str(target))
            if isinstance(scan, dict) and not scan.get("safe", True):
                return {
                    "status": "blocked",
                    "reason": "virus_scan_flagged",
                    "scan": scan,
                    "path": str(target),
                }
        except Exception:
            # Scanning is best effort unless an explicit detection is returned.
            pass
        result = self.docs.ingest(str(target))
        try:
            if getattr(self, "_fs_watcher", None) is not None and isinstance(result, dict):
                ingested_path = result.get("filepath") or str(target)
                self._fs_watcher.add_path(str(ingested_path))
        except Exception:
            pass
        return result

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
        if not hasattr(self, "_goal_persist_lock"):
            self._goal_persist_lock = threading.Lock()
        if not hasattr(self, "_goal_persist_timer"):
            self._goal_persist_timer = None
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
                    if item.get("status") in {"planning", "pending", "running", "approved_for_step", "awaiting_confirmation"}:
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
                        if not item.get("steps"):
                            item["status"] = "planning"
                            self._persist_goals()
                            with self._goal_plan_submit_lock:
                                if self._goal_plan_jobs_inflight >= self._max_goal_plan_jobs:
                                    item["status"] = "failed"
                                    item["last_result"] = {"status": "failed", "reason": "goal_planning_queue_full"}
                                    self._persist_goals()
                                    return {"goal_id": goal_id, "status": "failed", "reason": "goal_planning_queue_full"}
                                self._goal_plan_jobs_inflight += 1
                            inflight_released = {"value": False}

                            def _release_plan_slot() -> None:
                                with self._goal_plan_submit_lock:
                                    if inflight_released["value"]:
                                        return
                                    inflight_released["value"] = True
                                    self._goal_plan_jobs_inflight = max(0, self._goal_plan_jobs_inflight - 1)
                            
                            def background_plan():
                                try:
                                    if self._shutting_down.is_set():
                                        return
                                    try:
                                        plan = self._plan_goal(item.get("goal", ""), max_steps=min(item.get("max_steps", 20), 30))
                                    except Exception as exc:
                                        plan = {"status": "failed", "reason": f"planning_exception:{exc}"}
                                    if self._shutting_down.is_set():
                                        return
                                    with self._goal_lock:
                                        for g in self._goals:
                                            if g.get("id") == goal_id:
                                                if g.get("status") == "cancelled":
                                                    break
                                                if plan.get("status") == "ok":
                                                    g["steps"] = plan["steps"]
                                                    g["status"] = "pending"
                                                else:
                                                    g["status"] = "failed"
                                                    g["last_result"] = plan
                                                self._persist_goals()
                                                break
                                finally:
                                    _release_plan_slot()
                            
                            try:
                                future = self._goal_plan_executor.submit(background_plan)
                            except Exception as exc:
                                _release_plan_slot()
                                item["status"] = "failed"
                                item["last_result"] = {"status": "failed", "reason": f"planning_submit_exception:{exc}"}
                                self._persist_goals()
                                return {"goal_id": goal_id, "status": "failed"}
                            def _on_done(fut):
                                if fut.cancelled():
                                    _release_plan_slot()
                                    return
                                exc = fut.exception()
                                if exc is not None:
                                    with self._goal_lock:
                                        for g in self._goals:
                                            if g.get("id") == goal_id and g.get("status") == "planning":
                                                g["status"] = "failed"
                                                g["last_result"] = {"status": "failed", "reason": f"planning_future_exception:{exc}"}
                                                self._persist_goals()
                                                break
                            future.add_done_callback(_on_done)
                            return {"goal_id": goal_id, "status": "planning"}
                        else:
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
            from concurrent.futures import TimeoutError as FuturesTimeout
            from concurrent.futures import ThreadPoolExecutor
            import socket as _socket

            def _run() -> list[str]:
                rows = _socket.getaddrinfo(hostname, None)
                return [r[4][0] for r in rows]

            with ThreadPoolExecutor(max_workers=1) as executor:
                fut = executor.submit(_run)
                try:
                    return fut.result(timeout=timeout_seconds)
                except FuturesTimeout:
                    fut.cancel()
                    return []

        svc = service.strip().lower()
        if not svc:
            return {"status": "error", "reason": "service_required"}

        key = (api_key or "").strip() or (self.master_api.get(svc) or "")
        if endpoint:
            # Security fix (4.3): Never inject an Authorization Bearer token over plain HTTP.
            # If a key is present and the endpoint is not HTTPS or localhost, reject it.
            parsed_scheme, parsed_host = "", ""
            resolved_addrs: list[str] = []
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
                    resolved_addrs = list({addr for addr in _resolve_host_with_timeout(parsed_host, timeout_seconds=5.0)})
                    if not resolved_addrs:
                        return {
                            "status": "error",
                            "reason": "dns_resolution_timeout_or_failure",
                        }
                    resolved_private = True
                    for ip in resolved_addrs:
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
            endpoint_to_connect = endpoint
            # Pin plain-HTTP auth connections to the resolved IP to prevent DNS rebinding.
            if key and parsed_scheme == "http" and resolved_addrs and parsed_host:
                try:
                    from urllib.parse import urlparse, urlunparse

                    parsed = urlparse(endpoint)
                    chosen_ip = sorted(resolved_addrs)[0]
                    netloc = f"[{chosen_ip}]" if ":" in chosen_ip else chosen_ip
                    if parsed.port:
                        netloc = f"{netloc}:{parsed.port}"
                    endpoint_to_connect = urlunparse(parsed._replace(netloc=netloc))
                    host_header = parsed_host if parsed.port is None else f"{parsed_host}:{parsed.port}"
                    merged_headers.setdefault("Host", host_header)
                except Exception:
                    endpoint_to_connect = endpoint
            if key and "Authorization" not in merged_headers:
                merged_headers["Authorization"] = f"Bearer {key}"
            self.master_mcp.connect_http(
                service=svc,
                endpoint=endpoint_to_connect,
                headers=merged_headers,
                timeout_seconds=timeout_seconds,
                discover=discover,
            )
        elif svc in BUILTIN_SERVICES:
            if not key and svc != "a2a":
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

    def _safety_scan_file(self, path: str) -> dict:
        return self._virus_scanner.scan_file(path)

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
                # Avoid spawning duplicate `ollama serve` processes.
                already_running = _sp.run(
                    ["pgrep", "-f", "ollama serve"],
                    stdout=_sp.DEVNULL,
                    stderr=_sp.DEVNULL,
                ).returncode == 0
                if not already_running:
                    _sp.Popen(["ollama", "serve"], stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)
            except Exception:
                pass

        self.health.register_subsystem(
            "llm_engine",
            check_fn=_check_llm_engine,
            restart_fn=_restart_llm_engine,
        )

        # Fix 4: Register midnight reset for daily hard cap
        try:
            if self.scheduler.scheduler.running:
                def _reset_hard_cap():
                    with self._usage_lock:
                        self._hard_cap_hit = False
                        self._hard_cap_hit_date = None
                    import logging
                    logging.getLogger(__name__).info("Daily token hard-cap reset at midnight.")

                self.scheduler.scheduler.add_job(
                    _reset_hard_cap,
                    "cron",
                    hour=0,
                    minute=0,
                    id="daily_hard_cap_reset",
                    replace_existing=True,
                )
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("Failed to schedule daily hard-cap reset: %s", exc)
        can_watch_screen = True
        try:
            if sys.platform.startswith("linux") and not os.environ.get("DISPLAY"):
                can_watch_screen = False
        except Exception:
            can_watch_screen = True
        if settings.PROACTIVE_WATCHER_ENABLED and can_watch_screen:
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
            threading.Thread(target=self.omniparser.ensure_running, daemon=True).start()
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("OmniParser startup check failed: %s", exc)
        self.health.start(interval_seconds=settings.HEALTH_MONITOR_INTERVAL)

        # ── Proactive Intelligence scheduled jobs ─────────────────────────────
        from datetime import datetime as _dt
        _log_pi = __import__('logging').getLogger(__name__)

        # Tier 2: Emotional trajectory update every 10 minutes
        def _emotion_trajectory_job() -> None:
            try:
                now = _dt.now()
                current_hour_key = (now.year, now.timetuple().tm_yday * 24 + now.hour)
                if self._error_counter_hour != current_hour_key:
                    self._error_counter_hour = current_hour_key
                    self._error_detections_this_hour = 0
                session_mins = (time.monotonic() - self._session_start_time) / 60.0
                self.emotion.proactive_update(
                    hour=now.hour,
                    weekday=now.weekday(),
                    recent_errors=self._error_detections_this_hour,
                    session_length_minutes=session_mins,
                )
            except Exception:
                pass
        try:
            self.scheduler.add_interval(fn=_emotion_trajectory_job, seconds=600, job_id="emotion_traj")
        except Exception as e:
            _log_pi.warning("[proactive] emotion job register failed: %s", e)

        # Tier 1: Process lifecycle monitor every 60 seconds
        _PROCESS_CTX_MAP = {
            "zoom": "meeting", "teams": "meeting", "webex": "meeting",
            "pycharm": "python_dev", "vscode": "coding", "code": "coding",
            "docker": "containerized_workload", "obs": "recording",
            "slack": "comms", "discord": "comms",
        }
        def _process_monitor_job() -> None:
            try:
                procs = win32_api.list_processes()
                current_set = {p.lower() for p in (procs or [])}
                appeared = current_set - self._last_process_set
                self._last_process_set = current_set
                for proc in appeared:
                    ctx = _PROCESS_CTX_MAP.get(proc)
                    if ctx == "meeting":
                        self.emotion.update_from_signal("cautious")
                        if settings.VOICE_BARGEIN_ENABLED:
                            self._muted = True
                            self._notify_telegram("🎙️ Looks like you're in a call — I've paused voice output.")
                    if ctx:
                        self._handle_proactive_alert(f"[process] {proc} started ({ctx} context)")
            except Exception:
                pass
        try:
            self.scheduler.add_interval(fn=_process_monitor_job, seconds=60, job_id="proc_mon")
        except Exception as e:
            _log_pi.warning("[proactive] process monitor register failed: %s", e)

        # Tier 4: Daily maintenance at 3am
        def _maintenance_job() -> None:
            try:
                self._maintenance.run_daily_maintenance()
            except Exception:
                pass
        try:
            self.scheduler.add_from_text(fn=_maintenance_job, schedule_text="every day at 03:00", job_id="maint_daily")
        except Exception as e:
            _log_pi.warning("[proactive] maintenance job register failed: %s", e)

        # Daily reset of hard-cap latch so autonomy-only periods are not blocked
        # until the next interactive ask_stream call.
        def _hard_cap_reset_job() -> None:
            try:
                with self._usage_lock:
                    self._hard_cap_hit = False
                    self._hard_cap_hit_date = None
            except Exception:
                pass
        try:
            self.scheduler.add_from_text(
                fn=_hard_cap_reset_job,
                schedule_text="every day at 00:00",
                job_id="hardcap_daily_reset",
            )
        except Exception as e:
            _log_pi.warning("[proactive] hard-cap reset job register failed: %s", e)

        # Tier 2: Weekly insight extraction on Sunday at 2:30am
        def _weekly_insight_job() -> None:
            try:
                from datetime import datetime as _dti, timezone as _tz
                if _dti.now(_tz.utc).weekday() == 6:  # Sunday
                    self._run_weekly_extraction_and_evolve()
            except Exception:
                pass
        try:
            self.scheduler.add_from_text(fn=_weekly_insight_job, schedule_text="every day at 02:30", job_id="insight_weekly")
        except Exception as e:
            _log_pi.warning("[proactive] insight job register failed: %s", e)

        # Feature kickoff: weekly shortcut compiler (Sunday 11:00 PM local time)
        def _shortcut_compile_job() -> None:
            try:
                self._compile_weekly_shortcuts()
            except Exception:
                pass
        try:
            self.scheduler.add_from_text(
                fn=_shortcut_compile_job,
                schedule_text="every sunday at 11:00 pm",
                job_id="pattern_shortcuts_weekly",
            )
        except Exception as e:
            _log_pi.warning("[proactive] weekly shortcut compiler register failed: %s", e)

        # Tier 5: Network context detect at 5-min intervals
        # (NetworkContextDetector runs its own thread; no extra scheduler job needed)

        # Tier 3: Drain queued alerts every 60s if attention state allows
        def _drain_queued_alerts() -> None:
            try:
                if not self._queued_alerts:
                    return
                alerts = []
                while self._queued_alerts:
                    alerts.append(self._queued_alerts.popleft())
                if not alerts:
                    return
                digest = "\n".join(f"• {a}" for a in alerts[:10])
                self._notify_telegram(f"📋 *While you were focused:*\n{digest}")
            except Exception:
                pass
        try:
            self.scheduler.add_interval(fn=_drain_queued_alerts, seconds=60, job_id="drain_alerts")
        except Exception as e:
            _log_pi.warning("[proactive] alert drain job register failed: %s", e)

        # Tier 3: Commitment deadline reminder daily at 9am
        def _commitment_reminder_job() -> None:
            try:
                from utils.commitment_extractor import Commitment
                from datetime import datetime as _dtime, timezone as _tz2
                import json as _json
                now = _dtime.now(_tz2.utc)
                results = self.memory.search(
                    "commitment deadline", self.session.current.session_id, top_k=10
                )
                for item in (results or []):
                    meta = item.get("metadata") or {}
                    if meta.get("source") != "commitment":
                        continue
                    dl_ts = meta.get("deadline_ts")
                    if not dl_ts:
                        continue
                    try:
                        from datetime import datetime as _dp
                        dl = _dp.fromisoformat(dl_ts)
                        diff_h = (dl - now.replace(tzinfo=None)).total_seconds() / 3600
                        if 0 < diff_h <= 48:
                            desc = item.get("memory") or item.get("text") or ""
                            self._notify_telegram(
                                f"⏰ *Commitment reminder:*\n{desc[:200]}\n"
                                f"_(due in {diff_h:.0f}h)_"
                            )
                    except Exception:
                        pass
            except Exception:
                pass
        try:
            self.scheduler.add_from_text(fn=_commitment_reminder_job, schedule_text="every day at 09:00", job_id="commit_remind")
        except Exception as e:
            _log_pi.warning("[proactive] commitment reminder failed: %s", e)

        # Phase 16: Nudge engine periodic checks.
        def _nudge_job() -> None:
            try:
                if not getattr(settings, "NUDGE_ENGINE_ENABLED", True):
                    return
                world = snapshot_environment(include_clipboard=False)
                active_app = str(world.get("foreground_app", "") or "")
                try:
                    topic_items = self._intent_graph.hot_topics(top_k=1)
                    topic = topic_items[0][0] if topic_items else ""
                except Exception:
                    topic = ""
                task_key = f"{topic}:{active_app}".strip(":")
                if task_key:
                    self._nudge_engine.update_context(task_key=task_key)
                self._nudge_engine.detect_break(idle_seconds=0.0, active_app=active_app)
                message, insistent = self._nudge_engine.maybe_nudge()
                if message:
                    prefix = "Nudge (insistent)" if insistent else "Nudge"
                    self._handle_proactive_alert(f"{prefix}: {message}")
            except Exception:
                pass

        try:
            self.scheduler.add_interval(
                fn=_nudge_job,
                seconds=max(30, int(getattr(settings, "NUDGE_CHECK_SECONDS", 300))),
                job_id="nudge_engine",
            )
        except Exception as e:
            _log_pi.warning("[proactive] nudge job register failed: %s", e)

        # Phase 17: daily A2A standup aggregation.
        def _a2a_daily_standup() -> None:
            try:
                if not self._a2a_enabled:
                    return
                peers = self._peer_registry.list_peers()
                if not peers:
                    return
                names = sorted([str(p.get("agent_name", "")) for p in peers if p.get("agent_name")])
                if not names or names[0] != self._a2a_agent_name:
                    return
                recent = self.recent_events(limit=25)
                lines = [f"- {e.get('kind')}: {str(e.get('message', ''))[:100]}" for e in recent[:10]]
                text = "A2A Daily Standup\n" + "\n".join(lines)
                self._notify_telegram(text)
            except Exception:
                pass

        try:
            self.scheduler.add_from_text(
                fn=_a2a_daily_standup,
                schedule_text="every day at 18:00",
                job_id="a2a_daily_standup",
            )
        except Exception as e:
            _log_pi.warning("[proactive] a2a standup job register failed: %s", e)

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
        if getattr(settings, "AMBIENT_MONITOR_ENABLED", False):
            try:
                self._ambient_listener.start()
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
            if self._health_http_thread is not None and not self._health_http_thread.is_alive():
                self._health_http_server = None
                self._health_http_thread = None
            else:
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

        try:
            server = ThreadingHTTPServer((str(settings.NOVA_HEALTH_BIND_HOST), int(settings.NOVA_HEALTH_PORT)), _ProbeHandler)
        except OSError as exc:
            import logging
            logging.getLogger(__name__).error(
                "Health probe bind failed on %s:%s: %s",
                settings.NOVA_HEALTH_BIND_HOST,
                settings.NOVA_HEALTH_PORT,
                exc,
            )
            return
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
            candidate_id = None
            with self._goal_lock:
                for item in self._goals:
                    if item.get("status") in {"pending", "approved_for_step"} and item.get("steps"):
                        candidate_id = item.get("id")
                        break
                if candidate_id:
                    for item in self._goals:
                        if item.get("id") != candidate_id:
                            continue
                        if item.get("status") == "cancelled":
                            goal = None
                            break
                        if item.get("status") in {"pending", "approved_for_step"} and item.get("steps"):
                            # If it was specifically approved, we will pass a flag down
                            goal = dict(item)
                            item["status"] = "running"
                            item["started_at"] = time.time()
                            break
            if not goal:
                try:
                    now = time.monotonic()
                    if now - self._last_behavior_goal_proposal_at >= 300.0:
                        self._proactive_engine.propose_from_behavior()
                        self._last_behavior_goal_proposal_at = now
                except Exception:
                    pass
                self._autonomy_stop.wait(min(1.0, poll))
                continue

            steps = goal.get("steps") or []
            max_steps = int(goal.get("max_steps") or settings.AUTONOMY_MAX_STEPS)
            start_index = int(goal.get("cursor") or 0)
            
            approved_for_step = goal.get("status") == "approved_for_step"
            try:
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
                                should_continue=lambda gid=str(goal.get("id")): not self._is_goal_cancelled(gid),
                            )
                            # Approved single-step runs must always advance the goal cursor
                            # to avoid re-running the same blocked/stopped step forever.
                            result.next_index = min(len(steps), start_index + 1)
                    else:
                        result = self.autonomy_runner.run(
                            steps,
                            max_steps=max_steps,
                            start_index=start_index,
                            on_step=lambda i, r, gid=goal.get("id"): self._on_goal_step_completed(str(gid), i, r),
                            confirm_callback=self._autonomy_confirm_callback,
                            should_continue=lambda gid=str(goal.get("id")): not self._is_goal_cancelled(gid),
                        )
            except Exception as exc:
                result = GoalResult(status="failed", reason=f"autonomy_runner_exception:{exc}", results=[], next_index=start_index)

            if approved_for_step and result.status == "completed":
                status = "pending" if result.next_index < len(steps) else "completed"
            else:
                status = "completed" if result.status == "completed" else "paused"
                if result.status == "cancelled":
                    status = "cancelled"
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

            # ── Tier 4: Goal outcome learning + auto-doc ──────────────────────
            if status == "completed":
                goal_session_id = str(goal.get("session_id") or self.session.current.session_id)
                self._memory_executor.submit(self._auto_document_goal_outcome, goal, result, goal_session_id)
                # Tier 5: Record success to template library and prompt evolver
                try:
                    elapsed = time.time() - float(goal.get("started_at") or time.time())
                    self._template_library.record_success(
                        goal_description=str(goal.get("goal", "")),
                        steps=steps,
                        completion_time=elapsed,
                        available_tools=set(self.dispatcher.registry.keys()) if hasattr(self.dispatcher, 'registry') else set(),
                    )
                    self._prompt_evolver.record_goal_outcome(goal_session_id, succeeded=True)
                except Exception:
                    pass
            elif status == "failed":
                # Tier 4: Goal outcome learning — attempt replanning
                self._memory_executor.submit(self._handle_goal_failure, goal, result)
                try:
                    goal_session_id = str(goal.get("session_id") or self.session.current.session_id)
                    self._prompt_evolver.record_goal_outcome(goal_session_id, succeeded=False)
                except Exception:
                    pass
            # ── Tier 3: Drain proposed goals that have waited their grace period
            if hasattr(self, '_proactive_engine'):
                try:
                    running_count = sum(1 for g in self._goals if g.get("status") == "running")
                    new_goals = self._proactive_engine.drain_auto_approvable(running_count)
                    if new_goals:
                        with self._goal_lock:
                            for ng in new_goals:
                                if not any(g.get("id") == ng.get("id") for g in self._goals):
                                    self._goals.append(ng)
                            self._persist_goals()
                except Exception:
                    pass
            # ─────────────────────────────────────────────────────────────────

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
                goal_session_id = str(goal.get("session_id") or self.session.current.session_id)
                self.session.add_turn_for_session(goal_session_id, "assistant", message)
            self._notify_autonomy_event(message)

    def shutdown(self) -> None:
        if getattr(self, "_shutdown_called", False):
            return
        self._shutdown_called = True
        self._shutting_down.set()
        if getattr(self, "health", None):
            self.health.stop()
        if settings.PROACTIVE_WATCHER_ENABLED:
            if getattr(self, "screen_watcher", None):
                self.screen_watcher.stop()
        phone_watcher = getattr(self, "phone_watcher", None)
        if settings.PHONE_WATCHER_ENABLED and phone_watcher is not None:
            phone_watcher.stop()
        try:
            self._ambient_listener.stop()
        except Exception:
            pass
        try:
            self._peer_registry.close()
        except Exception:
            pass
        try:
            self._automation_factory.stop()
        except Exception:
            pass
        if getattr(self, "scheduler", None):
            self.scheduler.stop()
        try:
            with self._goal_persist_lock:
                timer = self._goal_persist_timer
                self._goal_persist_timer = None
            if timer and timer.is_alive():
                timer.cancel()
            with self._goal_lock:
                for item in self._goals:
                    if item.get("status") == "planning":
                        item["status"] = "failed"
                        if "last_result" not in item:
                            item["last_result"] = {"status": "failed", "reason": "goal_planning_interrupted_by_shutdown"}
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
        if self.memory.online:
            try:
                self.memory.sync_all_pending()
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
            close_thread = threading.Thread(
                target=lambda: (
                    self.goal_runner.close(cancel_futures=True),
                    self.autonomy_runner.close(cancel_futures=True),
                ),
                daemon=True,
            )
            close_thread.start()
            close_thread.join(timeout=5.0)
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
        self._self_eval_executor.shutdown(wait=False, **kwargs)
        # Drain queued TTS items so shutdown doesn't wait behind stale backlog.
        try:
            while True:
                try:
                    self._tts_queue.get_nowait()
                    self._tts_queue.task_done()
                except queue.Empty:
                    break
            self._tts_queue.put(None)   # sentinel to stop the worker
            self._tts_thread.join(timeout=5)
        except Exception:
            pass
        try:
            from voice.tts_offline import shutdown as shutdown_offline_tts
            shutdown_offline_tts(drain=True)
        except Exception:
            pass

    def __del__(self):
        return

    def _handle_proactive_alert(self, message: str) -> None:
        if "potentially malicious on-screen text" in message.lower():
            self.record_event("security", message)
        if "error" in message.lower() or "crash" in message.lower():
            now = datetime.now()
            hour_key = (now.year, now.timetuple().tm_yday * 24 + now.hour)
            if self._error_counter_hour != hour_key:
                self._error_counter_hour = hour_key
                self._error_detections_this_hour = 0
            self._error_detections_this_hour = getattr(self, '_error_detections_this_hour', 0) + 1
        self.record_event("proactive", message)
        if self._muted:
            return
        # ── Tier 3: Attention-aware interrupt scheduling ──────────────────────
        # Queue non-urgent alerts during deep focus; drain happens in scheduler job
        _is_urgent = any(kw in message.lower() for kw in ("error", "crash", "security", "disk", "failed"))
        if not _is_urgent and hasattr(self, '_queued_alerts'):
            self._queued_alerts.append(message)
            return
        # ─────────────────────────────────────────────────────────────────────
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

    def _notify_telegram(self, text: str, timeout_seconds: int = 12) -> dict | None:
        if self._get_session_privacy_mode() == "local_only":
            return None
        if not settings.AUTONOMY_NOTIFY_TELEGRAM:
            return None
        try:
            result = send_telegram_text(
                bot_token=settings.TELEGRAM_BOT_TOKEN,
                chat_id=settings.TELEGRAM_CHAT_ID,
                text=text,
                timeout_seconds=timeout_seconds,
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
                if not getattr(self, "_tts_warning_printed", False):
                    print("[tts] Warning: pyttsx3 not installed. Voice output unavailable.")
                    self._tts_warning_printed = True
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

    def _is_goal_cancelled(self, goal_id: str) -> bool:
        with self._goal_lock:
            for item in self._goals:
                if item.get("id") == goal_id:
                    return item.get("status") == "cancelled"
        return True

    def _notify_autonomy_event(self, text: str) -> None:
        self.record_event("autonomy", text)
        is_critical = any(k in text.lower() for k in ("failed", "blocked", "error", "stopped", "cancelled"))
        if self._muted and not is_critical:
            return
        _ = self._notify_telegram(text)
        if not self._muted:
            _ = self._notify_tts(text)

    def _register_adb_tools(self) -> bool:
        if not getattr(self, "adb", None):
            return False
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
        return True

    def _reload_adb_tools(self) -> dict:
        import shutil
        if getattr(self, "adb", None) is None:
            if not shutil.which("adb"):
                return {"status": "error", "reason": "adb_binary_not_found"}
            try:
                self.adb = ADBClient()
            except Exception as exc:
                return {"status": "error", "reason": f"adb_init_failed:{exc}"}
        registered = self._register_adb_tools()
        return {"status": "ok" if registered else "error", "registered": bool(registered)}

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
            self._register_adb_tools()
        self.dispatcher.register(
            "adb.reload_tools",
            self._reload_adb_tools,
            EmptyArgs,
            description="Re-detect ADB and (re)register adb.* tools if available.",
        )
        self.dispatcher.register("task.schedule", self._schedule_prompt, TaskScheduleArgs)
        self.dispatcher.register("task.list", self._list_jobs, EmptyArgs)
        self.dispatcher.register("task.cancel", self._cancel_job, TaskCancelArgs)
        self.dispatcher.register("mission.add", self._mission_add, MissionAddArgs)
        self.dispatcher.register("mission.list", self._mission_list, EmptyArgs)
        self.dispatcher.register("mission.enable", self._mission_enable, MissionToggleArgs)
        self.dispatcher.register("mission.disable", self._mission_disable, MissionToggleArgs)
        self.dispatcher.register("mission.run_now", self._mission_run_now, MissionRunArgs)
        self.dispatcher.register(
            "shortcut.compile",
            lambda: self._compile_weekly_shortcuts(),
            EmptyArgs,
            description="Compile repeated tool usage patterns into reusable shortcuts.",
        )
        self.dispatcher.register(
            "shortcut.list",
            self._shortcut_list,
            EmptyArgs,
            description="List compiled automatic shortcuts generated from repeated usage patterns.",
        )
        self.dispatcher.register(
            "shortcut.run",
            self._shortcut_run,
            ShortcutRunArgs,
            description="Run a compiled shortcut sequence by name.",
        )
        self.dispatcher.register(
            "learn.skill",
            self._learn_skill,
            LearnSkillArgs,
            description="Learn software docs and propose a control plugin scaffold.",
        )
        self.dispatcher.register(
            "learn.api",
            self._learn_api,
            ApiAutodiscoveryArgs,
            description="Autodiscover API docs and propose a client plugin scaffold.",
        )
        self.dispatcher.register(
            "learn.game_bot",
            self._learn_game_bot,
            GameBotArgs,
            description="Generate a game-bot strategy plugin scaffold.",
        )
        self.dispatcher.register(
            "learn.app",
            self._learn_app,
            LearnAppArgs,
            description="Generate an app-control plugin scaffold for a target app.",
        )
        self.dispatcher.register(
            "live.feed",
            self._live_feed_builder,
            LiveFeedArgs,
            description="Build a live data feed plugin and schedule periodic polling.",
        )
        self.dispatcher.register(
            "home.discover",
            self._home_discover,
            EmptyArgs,
            description="Scan LAN devices and write smart-home plugin stubs.",
        )
        self.dispatcher.register(
            "batch.api_plugins",
            self._batch_api_plugins,
            BatchApiArgs,
            description="Queue many API plugin-generation jobs for batch execution.",
        )
        self.dispatcher.register(
            "batch.status",
            self._batch_status,
            EmptyArgs,
            description="Show queued/running/done state for batch plugin jobs.",
        )
        self.dispatcher.register(
            "recovery.write",
            self._failure_recovery_write,
            FailureRecoveryArgs,
            description="Generate targeted recovery plugin after repeated failures.",
        )
        self.dispatcher.register(
            "mode.write",
            self._context_mode_write,
            ContextModeArgs,
            description="Generate a context-aware mode plugin for a situation label.",
        )
        self.dispatcher.register("model.list", list_ollama_models, EmptyArgs)
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
        self.dispatcher.register("safety.scan_file", self._safety_scan_file, SafetyScanFileArgs)
        self.dispatcher.register("session.export", self._session_export_tool, ExportSessionArgs)
        self.dispatcher.register("assistant.set_mute", self._set_mute_tool, SetMuteArgs)
        self.dispatcher.register("assistant.mute_status", self._mute_status_tool, EmptyArgs)
        self.dispatcher.register("a2a.peers", self._a2a_peers, EmptyArgs)
        self.dispatcher.register("a2a.send", self._a2a_send, A2ASendArgs)
        self.dispatcher.register("a2a.inbox", self._a2a_inbox, A2AInboxArgs)
        self.dispatcher.register("a2a.claim_file", self._a2a_claim_file, A2AClaimArgs)
        self.dispatcher.register("a2a.release_file", self._a2a_release_file, A2AClaimArgs)
        self.dispatcher.register("a2a.delegate_tool", self._a2a_delegate_tool, A2ADelegateArgs)
        # ── Feature 14: cross-platform window manager tools ───────────────────
        if self._window_manager is not None:
            self.dispatcher.register(
                "window.list", lambda: self._window_manager.list_windows(), WindowListArgs,
                description="List all visible windows on the desktop.",
            )
            self.dispatcher.register(
                "window.focus", lambda title: self._window_manager.focus(title), WindowFocusArgs,
                description="Bring a window to the foreground by title.",
            )
            self.dispatcher.register(
                "window.resize",
                lambda title, width, height: self._window_manager.resize(title, width, height),
                WindowResizeWMArgs,
                description="Resize a window to the specified pixel dimensions.",
            )
            self.dispatcher.register(
                "window.close", lambda title: self._window_manager.close(title), WindowCloseArgs,
                description="Close a window by title.",
            )
        # ── Feature 6: web scraper levels 3-4 ────────────────────────────────
        self.dispatcher.register(
            "web.scrape_js", scrape_js, ScrapeJsArgs,
            description="Scrape a JS-rendered page using a headless browser (Playwright).",
        )
        self.dispatcher.register(
            "web.scrape_visual",
            lambda url: scrape_visual(url, omniparser_url=settings.OMNIPARSER_SERVER_URL),
            ScrapeVisualArgs,
            description="Screenshot a page and run OmniParser UI-element detection on it.",
        )
        # ── Feature 8: self-writing plugin generator ──────────────────────────
        def _llm_for_plugin(system: str, user: str) -> str:
            return "".join(
                self.engine.ask_stream(prompt=user, system=system, history=[])
            )
        self._plugin_generator = PluginGenerator(
            llm_callable=_llm_for_plugin,
            dispatcher=self.dispatcher,
            scan_code_callback=lambda code, filename: self._virus_scanner.scan_text_buffer(code, filename),
        )
        self.dispatcher.register(
            "plugin.generate",
            lambda description: self._plugin_generator.generate_and_propose(description),
            PluginGenerateArgs,
            description=(
                "Generate a new NOVA plugin from a natural-language description. "
                "The generated code is shown for human approval before being loaded."
            ),
        )

        # ── Proactive Intelligence exposed tools ───────────────────────────────
        self.dispatcher.register(
            "behavior.profile",
            lambda: self._behavior_model.get_profile_summary(),
            EmptyArgs,
            description=(
                "Return the behavioral rhythm profile: predicted next activities "
                "based on historical patterns for the current time slot."
            ),
        )
        self.dispatcher.register(
            "tool.stats",
            lambda: self._tool_profiler.all_stats(),
            EmptyArgs,
            description=(
                "Return reliability statistics for all tools: success rate, "
                "average latency, and top failure reasons."
            ),
        )
        self.dispatcher.register(
            "intent.graph",
            lambda: self._intent_graph.summary(),
            EmptyArgs,
            description=(
                "Return a summary of the intent co-occurrence graph: "
                "hot topics and node count."
            ),
        )
        self.dispatcher.register(
            "goal.templates",
            lambda: {"templates": self._template_library.all_templates()},
            EmptyArgs,
            description=(
                "List all learned goal templates including trigger keywords, "
                "steps, and success counts."
            ),
        )
        self.dispatcher.register(
            "insight.weekly",
            lambda: self._run_weekly_extraction_and_evolve() or {"status": "extraction_queued"},
            EmptyArgs,
            description=(
                "Manually trigger a cross-session weekly insight extraction "
                "and surface the results."
            ),
        )

    def _run_weekly_extraction_and_evolve(self) -> dict | None:
        insight = self._insight_extractor.run_weekly_extraction()
        try:
            session_id = self.session.current.session_id
            averages = self._self_evaluator.weekly_averages(session_prefix=session_id[:8])
            self.memory.add(
                text=(
                    "Self-eval weekly averages: "
                    f"relevance={averages.get('relevance')} "
                    f"actionability={averages.get('actionability')} "
                    f"conciseness={averages.get('conciseness')}"
                ),
                session_id=session_id,
                metadata={"source": "self_evaluator"},
            )
        except Exception:
            pass
        if insight:
            self._prompt_evolver.propose_variant(insight, self.base_system_prompt)
            return {"status": "ok", "insight_generated": True}
        return None

    def _ensure_default_missions(self) -> None:
        try:
            existing = {m.get("name") for m in self._mission_manager.list_missions()}
        except Exception:
            return
        defaults = [
            ("morning_brief", "every day at 08:00", "Summarize overnight updates and give a concise morning brief."),
            ("daily_backup", "every day at 03:00", "Check backups and summarize backup health."),
            ("weekly_summary", "every monday at 09:00", "Summarize last week progress, blockers, and top priorities."),
            ("code_review_check", "every day at 18:00", "Review pending PRs and report high-risk findings."),
        ]
        for name, schedule_text, goal in defaults:
            if name in existing:
                continue
            try:
                self._mission_manager.add_mission(name=name, schedule=schedule_text, goal=goal, enabled=False)
            except Exception:
                continue

    def _handle_ambient_event(self, event: AmbientEvent) -> None:
        try:
            msg = f"Ambient event: {event.event_type} (confidence {event.confidence:.2f})"
            if event.detail:
                msg += f" [{event.detail}]"
            self._handle_proactive_alert(msg)
        except Exception:
            pass

    def _ambient_transcribe(self, wav_bytes: bytes, sample_rate: int) -> str:
        _ = sample_rate
        if not wav_bytes:
            return ""
        try:
            with self._ambient_whisper_lock:
                if self._ambient_whisper is None:
                    from voice.stt_offline import OfflineWhisper

                    self._ambient_whisper = OfflineWhisper(model_size=settings.WHISPER_MODEL)
                whisper = self._ambient_whisper
            return whisper.transcribe(wav_bytes, lang=settings.DEFAULT_LANG)
        except Exception:
            return ""

    def _mission_add(self, name: str, schedule: str, goal: str, enabled: bool = True) -> dict:
        return self._mission_manager.add_mission(name=name, schedule=schedule, goal=goal, enabled=enabled)

    def _mission_list(self) -> dict:
        return {"missions": self._mission_manager.list_missions()}

    def _mission_enable(self, name: str) -> dict:
        return self._mission_manager.enable_mission(name, True)

    def _mission_disable(self, name: str) -> dict:
        return self._mission_manager.enable_mission(name, False)

    def _mission_run_now(self, name: str) -> dict:
        return self._mission_manager.run_mission_now(name)

    def _compile_weekly_shortcuts(self) -> dict:
        result = self._shortcut_compiler.compile(lookback_days=7, min_repeats=3, max_sequence_len=3, top_k=10)
        count = len(result.get("shortcuts", []))
        self.record_event("shortcut", f"Compiled {count} shortcuts from weekly action history.")
        return {"status": "ok", "compiled_count": count, "shortcuts": result.get("shortcuts", [])}

    def _shortcut_list(self) -> dict:
        rows = self._shortcut_compiler.list_shortcuts()
        return {"shortcuts": rows, "count": len(rows)}

    def _shortcut_run(self, name: str, dry_run: bool = False) -> dict:
        return self._shortcut_compiler.run_shortcut(name=name, dispatcher=self.dispatcher, dry_run=dry_run)

    def _learn_skill(self, skill_name: str) -> dict:
        return self._automation_factory.learn_skill(skill_name)

    def _learn_api(self, api_name: str) -> dict:
        return self._automation_factory.api_autodiscovery(api_name)

    def _learn_game_bot(self, game_name: str) -> dict:
        return self._automation_factory.game_bot_generator(game_name)

    def _learn_app(self, app_name: str) -> dict:
        return self._automation_factory.app_reverse_engineer(app_name)

    def _live_feed_builder(self, topic: str, interval_minutes: int = 5) -> dict:
        return self._automation_factory.live_data_feed_builder(topic, interval_minutes=interval_minutes)

    def _home_discover(self) -> dict:
        return self._automation_factory.smart_home_discoverer()

    def _batch_api_plugins(self, api_names: list[str]) -> dict:
        return self._automation_factory.enqueue_batch_api_plugins(api_names)

    def _batch_status(self) -> dict:
        return self._automation_factory.batch_status()

    def _failure_recovery_write(self, step_key: str, screenshot_path: str = "") -> dict:
        return self._automation_factory.record_failure_and_recover(step_key=step_key, screenshot_path=screenshot_path)

    def _context_mode_write(self, context_label: str) -> dict:
        return self._automation_factory.context_mode_writer(context_label)

    def _a2a_role(self) -> dict:
        tools = list(self.dispatcher.registry.keys()) if hasattr(self.dispatcher, "registry") else []
        role = assign_role(
            tools=tools,
            can_run_tests=any("pytest" in t for t in tools) or bool(shutil.which("pytest")),
            has_git=bool(shutil.which("git")),
            has_rag=any(t.startswith("doc.") for t in tools),
        )
        return {"agent_name": self._a2a_agent_name, "role": role.role, "rationale": role.rationale}

    def _a2a_register_presence(self) -> dict:
        tools = list(self.dispatcher.registry.keys()) if hasattr(self.dispatcher, "registry") else []
        cap_hash = hashlib.sha256(",".join(sorted(tools)).encode("utf-8")).hexdigest()[:16]
        return self._peer_registry.upsert_self(
            agent_name=self._a2a_agent_name,
            session=self.session.current.name,
            tools=tools,
            capabilities_hash=cap_hash,
            health_port=int(getattr(settings, "NOVA_HEALTH_PORT", 8765)),
        )

    def _a2a_peers(self) -> dict:
        mdns = self._peer_registry.discover_mdns_peers(timeout_seconds=1.0)
        local = self._peer_registry.list_peers()
        tailscale = self._peer_registry.discover_tailscale_peers()
        return {
            "local_registry": local,
            "mdns_peers": mdns,
            "tailscale_peers": tailscale,
            "role": self._a2a_role(),
        }

    def _a2a_send(self, to_agent: str, msg_type: str = "status_update", payload: dict | None = None) -> dict:
        if payload is None:
            payload = {}
        return self._shared_bus.publish(
            from_agent=self._a2a_agent_name,
            to_agent=to_agent,
            msg_type=msg_type,
            payload=payload,
        )

    def _a2a_inbox(self, limit: int = 50) -> dict:
        rows = self._shared_bus.read(to_agent=self._a2a_agent_name, limit=max(1, min(int(limit), 200)))
        return {"messages": rows}

    def _a2a_claim_file(self, path: str) -> dict:
        result = self._conflict_resolver.claim_file(agent_name=self._a2a_agent_name, filepath=path)
        if result.get("status") == "conflict":
            payload = {
                "path": str(path),
                "held_by": result.get("held_by"),
                "winner": result.get("winner"),
                "paused_agent": result.get("paused_agent"),
                "ts": int(time.time()),
            }
            try:
                self._a2a_send(to_agent="broadcast", msg_type="conflict_alert", payload=payload)
                self.record_event("a2a", f"conflict_alert: {payload}")
                result["alert_sent"] = True
            except Exception:
                result["alert_sent"] = False
        return result

    def _a2a_release_file(self, path: str) -> dict:
        return self._conflict_resolver.release_file(agent_name=self._a2a_agent_name, filepath=path)

    def _a2a_delegate_tool(
        self,
        to_agent: str,
        tool_name: str,
        args: dict | None = None,
        service: str | None = None,
    ) -> dict:
        payload_args = dict(args or {})
        target_service = (service or to_agent).strip()
        if target_service and self.master_mcp.is_connected(target_service):
            result = self.master_mcp.call_tool(target_service, tool_name, **payload_args)
            return {
                "status": "executed",
                "service": target_service,
                "to_agent": to_agent,
                "tool_name": tool_name,
                "result": result,
            }

        request_id = uuid.uuid4().hex[:12]
        self._a2a_send(
            to_agent=to_agent,
            msg_type="tool_delegation",
            payload={
                "request_id": request_id,
                "tool_name": tool_name,
                "args": payload_args,
                "requested_by": self._a2a_agent_name,
                "ts": int(time.time()),
            },
        )
        return {
            "status": "queued",
            "request_id": request_id,
            "to_agent": to_agent,
            "tool_name": tool_name,
            "reason": "target_service_not_connected_locally",
        }

    def _run_leaving_home_routine(self) -> dict:
        service = "home_assistant"
        if not self.master_mcp.is_connected(service):
            return {"status": "error", "reason": "home_assistant_not_connected"}

        result: dict[str, Any] = {"status": "ok", "steps": []}

        def _step(name: str, payload: Any) -> None:
            result["steps"].append({"step": name, "result": payload})

        try:
            automations = self.master_mcp.call_tool(service, "list_automations")
            chosen = ""
            if isinstance(automations, list):
                for item in automations:
                    if not isinstance(item, dict):
                        continue
                    entity_id = str(item.get("entity_id", "")).lower()
                    friendly = str(item.get("friendly_name", "")).lower()
                    if any(k in entity_id or k in friendly for k in ("leave", "away", "leaving_home", "goodbye")):
                        chosen = str(item.get("entity_id", "")).strip()
                        break
            if chosen:
                _step("trigger_automation", self.master_mcp.call_tool(service, "trigger_automation", automation_id=chosen))
        except Exception as exc:
            _step("trigger_automation", {"ok": False, "error": str(exc)})

        try:
            locks = self.master_mcp.call_tool(service, "list_entities", domain="lock")
            if isinstance(locks, list):
                for item in locks[:3]:
                    entity_id = str((item or {}).get("entity_id", "")).strip()
                    if not entity_id:
                        continue
                    _step(
                        f"lock:{entity_id}",
                        self.master_mcp.call_tool(service, "call_service", domain="lock", service="lock", entity_id=entity_id),
                    )
        except Exception as exc:
            _step("lock_entities", {"ok": False, "error": str(exc)})

        try:
            alarms = self.master_mcp.call_tool(service, "list_entities", domain="alarm_control_panel")
            if isinstance(alarms, list) and alarms:
                alarm_id = str((alarms[0] or {}).get("entity_id", "")).strip()
                if alarm_id:
                    _step(
                        f"alarm:{alarm_id}",
                        self.master_mcp.call_tool(
                            service,
                            "call_service",
                            domain="alarm_control_panel",
                            service="alarm_arm_away",
                            entity_id=alarm_id,
                        ),
                    )
        except Exception as exc:
            _step("arm_alarm", {"ok": False, "error": str(exc)})

        try:
            climates = self.master_mcp.call_tool(service, "list_entities", domain="climate")
            if isinstance(climates, list) and climates:
                climate_id = str((climates[0] or {}).get("entity_id", "")).strip()
                if climate_id:
                    _step(
                        f"climate:{climate_id}",
                        self.master_mcp.call_tool(service, "set_climate", entity_id=climate_id, temperature=24.0),
                    )
        except Exception as exc:
            _step("set_climate", {"ok": False, "error": str(exc)})

        return result

    def _context_messages(
        self,
        user_text: str,
        *,
        session_id: str | None = None,
        history: list[dict] | None = None,
    ) -> tuple[str, list[dict], list[dict]]:
        if session_id is None or history is None:
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
                    epoch = self._session_context_epoch.get(session_id, 0)

                    def _job(sn=snippet, sid=session_id, sid_epoch=epoch):
                        try:
                            self._summarize_history_background(sn, sid, sid_epoch)
                        finally:
                            with self._summary_submit_lock:
                                self._summary_inflight.discard(sid)
                                self._summary_jobs_inflight = max(0, self._summary_jobs_inflight - 1)

                    if self._summary_jobs_inflight < self._max_background_summary_jobs:
                        self._summary_jobs_inflight += 1
                        try:
                            self._summarize_executor.submit(_job)
                        except Exception:
                            self._summary_inflight.discard(session_id)
                            self._summary_jobs_inflight = max(0, self._summary_jobs_inflight - 1)
                            self._summary_retry_after[session_id] = time.time() + 10.0
        
        summary, recent = self.trimmer.trim(
            history,
            session_id=session_id,
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
            capability_summary=self._capability_summary or None,
        )
        try:
            prompt_suffix = self._prompt_evolver.get_active_suffix(session_id)
            if prompt_suffix:
                system_prompt = f"{system_prompt}\n\n{prompt_suffix}"
        except Exception:
            pass

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
        # Drop to a fast truncation so we don't completely lose context.
        return text[:700]
    
    def _summarize_history_background(self, text: str, session_id: str, session_epoch: int) -> None:
        """Summarize history in background thread and update cache."""
        if not text.strip():
            return
            
        try:
            system = "Summarize the conversation history into a concise paragraph for future context."
            summary = self.engine.ask(prompt=text, system=system, history=[])
            self._track_usage(system, [], "[history_summary]", summary, session_id=session_id)
            if not str(summary).strip():
                return
            # Fix 3.2 & 11: Lock around LRU ordered dict cache 
            with self._summary_cache_lock:
                stable_hash = hashlib.sha256(f"{session_id}:{text}".encode("utf-8")).hexdigest()
                self._summary_cache[stable_hash] = summary
                if len(self._summary_cache) > 50:
                    self._summary_cache.popitem(last=False)
            with self._summary_submit_lock:
                current_epoch = self._session_context_epoch.get(session_id, 0)
                if current_epoch != session_epoch:
                    return
            with self.trimmer._lock:
                self.trimmer.summaries[session_id] = summary
            stale_summary = False
            with self._summary_submit_lock:
                current_epoch = self._session_context_epoch.get(session_id, 0)
                stale_summary = current_epoch != session_epoch
                # Cool down re-summarization churn after a successful summary.
                self._summary_retry_after[session_id] = time.time() + 30.0
            if stale_summary:
                with self.trimmer._lock:
                    if self.trimmer.summaries.get(session_id) == summary:
                        self.trimmer.summaries.pop(session_id, None)
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
                awaiting = [g for g in self._goals if g.get("status") == "awaiting_confirmation"]
                if candidate_id:
                    for goal in awaiting:
                        if goal.get("id") == candidate_id:
                            goal["status"] = "approved_for_step"
                            self._persist_goals()
                            return f"Goal {candidate_id} approved for next step."
                else:
                    if len(awaiting) == 1:
                        awaiting[0]["status"] = "approved_for_step"
                        self._persist_goals()
                        return f"Goal {awaiting[0]['id']} approved for next step."
                    if len(awaiting) > 1:
                        pending_ids = ", ".join(str(g.get("id")) for g in awaiting[:8])
                        return f"Multiple goals await confirmation. Use /approve_goal <goal_id>. Pending: {pending_ids}"
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
        if text in {f"{agent} use local mode", "use local mode"}:
            mode = self._set_session_privacy_mode("local_only")
            return f"Session privacy mode set to {mode}. Cloud LLM, mem0 sync, and Telegram notifications are disabled for this session."
        if text in {f"{agent} use cloud mode", "use cloud mode"}:
            mode = self._set_session_privacy_mode("full_cloud")
            return f"Session privacy mode set to {mode}. Full cloud features are enabled for this session."
        if text in {f"{agent} use balanced mode", "use balanced mode"}:
            mode = self._set_session_privacy_mode("balanced")
            return f"Session privacy mode set to {mode}. Cloud LLM stays enabled while remote memory sync remains disabled."
        if text in {"privacy mode", f"{agent} privacy mode"}:
            mode = self._get_session_privacy_mode()
            return f"Current session privacy mode: {mode}."
        if text in {f"{agent} no nudges today", "no nudges today"}:
            self._nudge_engine.mute_today()
            return "Nudges muted for today."
        if text.startswith("schedule mission ") or text.startswith(f"{agent} schedule mission "):
            parsed = self._mission_manager.parse_and_add_from_text(user_text)
            return str(parsed)
        if text.startswith("/mission "):
            cmd_body = user_text.strip()[len("/mission ") :].strip()
            if cmd_body.lower() == "list":
                return json.dumps(self._mission_list(), ensure_ascii=False, indent=2)
            if cmd_body.lower().startswith("enable "):
                return str(self._mission_enable(cmd_body.split(" ", 1)[1].strip()))
            if cmd_body.lower().startswith("disable "):
                return str(self._mission_disable(cmd_body.split(" ", 1)[1].strip()))
            if cmd_body.lower().startswith("run "):
                return str(self._mission_run_now(cmd_body.split(" ", 1)[1].strip()))
            if cmd_body.lower().startswith("add "):
                raw = cmd_body[4:].strip()
                parts = [p.strip() for p in raw.split("|")]
                if len(parts) != 3:
                    return "Usage: /mission add <name> | <schedule> | <goal>"
                return str(self._mission_add(parts[0], parts[1], parts[2], True))
            return "Usage: /mission list|enable <name>|disable <name>|run <name>|add ..."
        if text.startswith("/shortcut "):
            cmd_body = user_text.strip()[len("/shortcut ") :].strip()
            if cmd_body.lower() == "list":
                return json.dumps(self._shortcut_list(), ensure_ascii=False, indent=2)
            if cmd_body.lower() == "compile":
                return json.dumps(self._compile_weekly_shortcuts(), ensure_ascii=False, indent=2)
            if cmd_body.lower().startswith("run "):
                name = cmd_body.split(" ", 1)[1].strip()
                if not name:
                    return "Usage: /shortcut run <name>"
                return json.dumps(self._shortcut_run(name=name, dry_run=False), ensure_ascii=False, indent=2)
            return "Usage: /shortcut list|compile|run <name>"
        if text.startswith("nova, learn ") or text.startswith("nova learn "):
            name = user_text.split("learn", 1)[1].strip()
            if not name:
                return "Usage: Nova, learn <software>"
            return json.dumps(self._learn_skill(name), ensure_ascii=False, indent=2)
        if text.startswith("nova, use ") and " api" in text:
            raw = user_text.split("use", 1)[1].strip()
            api_name = re.sub(r"\s+api\s*$", "", raw, flags=re.IGNORECASE).strip() or raw
            return json.dumps(self._learn_api(api_name), ensure_ascii=False, indent=2)
        if text.startswith("nova, play ") or text.startswith("nova play "):
            game = user_text.split("play", 1)[1].strip()
            if not game:
                return "Usage: Nova, play <game>"
            return json.dumps(self._learn_game_bot(game), ensure_ascii=False, indent=2)
        if text.startswith("nova, learn this app") or text.startswith("nova learn this app"):
            return json.dumps(self._learn_app("current_app"), ensure_ascii=False, indent=2)
        if text.startswith("nova, live ") or text.startswith("nova live "):
            topic = user_text.split("live", 1)[1].strip()
            if not topic:
                return "Usage: Nova, live <topic>"
            return json.dumps(self._live_feed_builder(topic=topic, interval_minutes=5), ensure_ascii=False, indent=2)
        if text == "nova, discover home" or text == "nova discover home":
            return json.dumps(self._home_discover(), ensure_ascii=False, indent=2)
        if text.startswith("support these ") and "api" in text:
            raw = user_text.strip()[len("support these ") :].strip()
            raw = re.sub(r"\bapis?\b", "", raw, flags=re.IGNORECASE).strip()
            names = [p.strip() for p in raw.split(",") if p.strip()]
            if not names:
                return "Usage: support these <api1, api2, ...> APIs"
            return json.dumps(self._batch_api_plugins(names), ensure_ascii=False, indent=2)
        if text.startswith("/batch api "):
            raw = user_text.strip()[len("/batch api ") :].strip()
            names = [p.strip() for p in raw.split(",") if p.strip()]
            if not names:
                return "Usage: /batch api <api1, api2, ...>"
            return json.dumps(self._batch_api_plugins(names), ensure_ascii=False, indent=2)
        if text == "/batch status":
            return json.dumps(self._batch_status(), ensure_ascii=False, indent=2)
        if text.startswith("/recover "):
            step = user_text.strip()[len("/recover ") :].strip()
            if not step:
                return "Usage: /recover <step_key>"
            return json.dumps(self._failure_recovery_write(step_key=step, screenshot_path=""), ensure_ascii=False, indent=2)
        if text.startswith("/mode "):
            ctx = user_text.strip()[len("/mode ") :].strip()
            if not ctx:
                return "Usage: /mode <context_label>"
            return json.dumps(self._context_mode_write(context_label=ctx), ensure_ascii=False, indent=2)
        if text.startswith("/a2a "):
            cmd_body = user_text.strip()[len("/a2a ") :].strip()
            if cmd_body.lower() == "peers":
                return json.dumps(self._a2a_peers(), ensure_ascii=False, indent=2)
            if cmd_body.lower().startswith("inbox"):
                parts = cmd_body.split()
                limit = 20
                if len(parts) > 1:
                    try:
                        limit = int(parts[1])
                    except Exception:
                        limit = 20
                return json.dumps(self._a2a_inbox(limit), ensure_ascii=False, indent=2)
            if cmd_body.lower().startswith("send "):
                raw = cmd_body[5:].strip()
                parts = [p.strip() for p in raw.split("|")]
                if len(parts) != 3:
                    return "Usage: /a2a send <to_agent> | <msg_type> | <json_payload>"
                try:
                    payload = json.loads(parts[2]) if parts[2] else {}
                except Exception as exc:
                    return f"Invalid JSON payload: {exc}"
                return str(self._a2a_send(parts[0], parts[1], payload))
            if cmd_body.lower().startswith("delegate "):
                raw = cmd_body[9:].strip()
                parts = [p.strip() for p in raw.split("|")]
                if len(parts) != 3:
                    return "Usage: /a2a delegate <to_agent> | <tool_name> | <json_args>"
                try:
                    payload = json.loads(parts[2]) if parts[2] else {}
                except Exception as exc:
                    return f"Invalid JSON args: {exc}"
                return str(self._a2a_delegate_tool(parts[0], parts[1], payload, None))
            return "Usage: /a2a peers|inbox [limit]|send ...|delegate ..."
        if text.startswith("/models"):
            from interfaces.model_manager import (
                benchmark_providers,
                delete_ollama_model,
                list_ollama_models,
                provider_key_snapshot,
                pull_ollama_model,
                recommend_provider,
            )

            cmd_body = user_text.strip()[len("/models") :].strip()
            sub = cmd_body.split(" ", 1)[0].lower() if cmd_body else "list"
            rest = cmd_body.split(" ", 1)[1].strip() if " " in cmd_body else ""
            if sub in {"", "list"}:
                rows = list_ollama_models()
                return json.dumps({"models": rows}, ensure_ascii=False, indent=2)
            if sub == "pull":
                if not rest:
                    return "Usage: /models pull <model_name>"
                return str(pull_ollama_model(rest))
            if sub in {"delete", "rm"}:
                if not rest:
                    return "Usage: /models delete <model_name>"
                return str(delete_ollama_model(rest))
            if sub in {"benchmark", "bench"}:
                return json.dumps({"benchmark": benchmark_providers(self)}, ensure_ascii=False, indent=2)
            if sub in {"recommend", "auto"}:
                return json.dumps(recommend_provider(self), ensure_ascii=False, indent=2)
            if sub in {"keys", "health"}:
                return json.dumps(provider_key_snapshot(self), ensure_ascii=False, indent=2)
            return "Usage: /models list|pull <name>|delete <name>|benchmark|recommend|keys"
        if text.startswith("/theme ") or text.startswith("theme "):
            requested = user_text.split(" ", 1)[1].strip()
            selected = self.set_theme_lock(requested)
            if selected == "auto":
                return "Theme auto-switch enabled."
            return f"Theme locked to '{selected}'."
        if any(phrase in text for phrase in {"i am leaving home", "leaving home", "headed out"}):
            return (
                "Before you leave, I can help run Home Assistant actions: "
                "lock doors, arm alarm, and set thermostat eco mode. "
                "Say: 'run leaving-home routine'."
            )
        if text in {"run leaving-home routine", "run leaving home routine", "leaving-home routine"}:
            return str(self._run_leaving_home_routine())
        if re.match(r"^switch session\s+.+$", text):
            m = re.match(r"^\s*switch\s+session\s+(.+?)\s*$", user_text, flags=re.IGNORECASE)
            name = (m.group(1) if m else "").strip()
            if not name:
                return "Session name is required."
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
        current_session = self.session.current
        current_session_id = current_session.session_id
        with current_session._lock:
            current_history = list(current_session.history)

        def _append_turn(role: str, content: str) -> None:
            if self.session.current.session_id != current_session_id:
                return
            with current_session._lock:
                current_session.history.append({"role": role, "content": content})
                max_turns = getattr(self.session, "_max_history_turns", 500)
                if len(current_session.history) > max_turns:
                    current_session.history = current_session.history[-max_turns:]
            self.session._persist_session(current_session)

        command_response = self._apply_text_commands(user_text)
        if command_response:
            yield command_response
            return

        today = date.today()
        if self._is_hard_cap_active_today(today):
            yield f"Daily token hard cap of {settings.DAILY_TOKEN_HARD_CAP} reached. Further calls blocked."
            return

        self.emotion.update_from_signal(user_text)
        try:
            today_key = date.today()
            if self._monday_insight_checked_on != today_key:
                self._insight_extractor.maybe_surface_monday_insight()
                self._monday_insight_checked_on = today_key
            now_dt = datetime.now()
            session_mins = (time.monotonic() - self._session_start_time) / 60.0
            self.emotion.proactive_update(
                hour=now_dt.hour,
                weekday=now_dt.weekday(),
                recent_errors=self._error_detections_this_hour,
                session_length_minutes=session_mins,
            )
        except Exception:
            pass
        privacy_mode = self._apply_privacy_mode_for_session(current_session_id)
        remote_memory_online = self._network_online_cached() and privacy_mode == "full_cloud"
        self.memory.set_online(remote_memory_online)
        if self.memory.online:
            self._schedule_sync_all_pending()

        if needs_clarification(user_text):
            question = clarifying_question(user_text)
            _append_turn("user", user_text)
            _append_turn("assistant", question)
            yield question
            return

        system_prompt, history, _ = self._context_messages(
            user_text,
            session_id=current_session_id,
            history=current_history,
        )
        hardcap = int(settings.DAILY_TOKEN_HARD_CAP)
        if hardcap > 0:
            projected_input = estimate_tokens(system_prompt) + estimate_tokens(user_text)
            projected_input += sum(estimate_tokens(str(m.get("content", ""))) for m in history)
            with self._usage_lock:
                current_total = int(self.usage.total_tokens_for_day(today, session_id=current_session_id))
            if current_total + projected_input >= hardcap:
                with self._usage_lock:
                    self._hard_cap_hit = True
                    self._hard_cap_hit_date = today
                yield (
                    f"Daily token hard cap of {hardcap} would be exceeded by this request. "
                    "Further calls are blocked for today."
                )
                return

        output_chunks: list[str] = []
        user_added = False
        committed = False
        usage_tracked = False
        assistant_text = ""

        with self.engine.local_only_mode(privacy_mode == "local_only"):
            stream = self.engine.ask_stream(prompt=user_text, system=system_prompt, history=history)
            try:
                try:
                    first_token = next(stream)
                    _append_turn("user", user_text)
                    user_added = True
                    output_chunks.append(first_token)
                    yield first_token
                    for token in stream:
                        output_chunks.append(token)
                        yield token
                except StopIteration:
                    if not user_added:
                        _append_turn("user", user_text)
                        user_added = True
                    assistant_text = "(no response)"
                except RuntimeError as exc:
                    # PEP 479: inner StopIteration may surface as RuntimeError.
                    if "StopIteration" in str(exc):
                        if not user_added:
                            _append_turn("user", user_text)
                            user_added = True
                        assistant_text = "(no response)"
                    else:
                        raise

                if not assistant_text:
                    assistant_text = "".join(output_chunks).strip()
                tool_call = self.dispatcher.try_parse_tool_call(assistant_text) if allow_tools else None
                if tool_call:
                    result = self.dispatcher.execute(
                        tool_call,
                        confirm_callback=self._interactive_confirm,
                        dry_run=dry_run_tools,
                    )
                    try:
                        status = str(result.get("status", "")).lower() if isinstance(result, dict) else ""
                        if status in {"blocked", "cancelled", "error", "rate_limited", "partial"}:
                            self._automation_factory.record_failure_and_recover(
                                step_key=tool_call.tool,
                                screenshot_path="assets/screen.png",
                            )
                    except Exception:
                        pass
                    try:
                        serialized_result = json.dumps(result, ensure_ascii=False)
                    except TypeError:
                        serialized_result = str(result)
                    tool_result_text = f"[tool_result] {serialized_result}"
                    if output_chunks:
                        yield "\n"
                    yield tool_result_text
                    assistant_text = tool_result_text

                if assistant_text:
                    _append_turn("assistant", assistant_text)
                    committed = True
                    self._track_usage(
                        system_prompt,
                        history,
                        user_text,
                        assistant_text,
                        day_anchor=today,
                        session_id=current_session_id,
                    )
                    usage_tracked = True
                    self._commit_memory_async(user_text, assistant_text, session_id=current_session_id)
                    self._schedule_self_eval(
                        user_text=user_text,
                        assistant_text=assistant_text,
                        session_id=current_session_id,
                    )
            except Exception as exc:
                yield f"[ERROR] Generation failed: {exc}"
            finally:
                # If caller abandons this generator mid-stream, persist partial output.
                if not committed and (user_added or output_chunks):
                    partial = assistant_text or "".join(output_chunks).strip()
                    if not partial:
                        return
                    if self._shutting_down.is_set():
                        partial = f"{partial}\n[truncated: shutdown]"
                    if not user_added:
                        _append_turn("user", user_text)
                        user_added = True
                    try:
                        if not usage_tracked:
                            self._track_usage(
                                system_prompt,
                                history,
                                user_text,
                                partial,
                                day_anchor=today,
                                session_id=current_session_id,
                            )
                    except Exception:
                        pass
                    if user_added:
                        _append_turn("assistant", partial)
                        self._commit_memory_async(user_text, partial, session_id=current_session_id)
                        self._schedule_self_eval(user_text=user_text, assistant_text=partial, session_id=current_session_id)

    def _schedule_self_eval(self, *, user_text: str, assistant_text: str, session_id: str) -> None:
        try:
            estimated = estimate_tokens(assistant_text)
            daily_total = int(self.usage.total_tokens_today(session_id=session_id))
            hard_cap = int(getattr(settings, "DAILY_TOKEN_HARD_CAP", 0) or 0)
            if hard_cap > 0:
                remaining = hard_cap - daily_total
                # Avoid spending the final budget on self-evaluation.
                if remaining <= max(2000, estimated * 2):
                    return
            if not self._self_evaluator.should_rate(
                assistant_text=assistant_text,
                estimated_tokens=estimated,
                daily_total_tokens=daily_total,
                daily_alert_threshold=int(settings.DAILY_TOKEN_ALERT_THRESHOLD),
                enabled=bool(getattr(settings, "SELF_EVAL_ENABLED", True)),
                min_response_tokens=int(getattr(settings, "SELF_EVAL_MIN_RESPONSE_TOKENS", 50)),
                skip_usage_pct=int(getattr(settings, "SELF_EVAL_SKIP_USAGE_PCT", 90)),
            ):
                return
        except Exception:
            return

        def _job() -> None:
            try:
                payload = self._self_evaluator.evaluate(
                    prompt=user_text,
                    response=assistant_text,
                    session_id=session_id,
                )
                self.record_event("self_eval", f"rated: {payload.get('ratings', {})}")
            except Exception:
                pass

        try:
            self._self_eval_executor.submit(_job)
        except Exception:
            pass

    def _a2a_publish_context_sync(self, *, user_text: str, assistant_text: str, session_id: str) -> None:
        if not self._a2a_enabled:
            return
        try:
            content = f"u:{user_text}\na:{assistant_text}"
            digest = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
            self._shared_bus.publish(
                from_agent=self._a2a_agent_name,
                to_agent="broadcast",
                msg_type="context_sync",
                payload={
                    "session_id": session_id,
                    "digest": digest,
                    "preview": assistant_text[:160],
                    "ts": int(time.time()),
                },
            )
        except Exception:
            pass

    def _commit_memory_async(self, user_text: str, assistant_text: str, session_id: str | None = None) -> None:
        if self._shutting_down.is_set():
            return
        session_id = session_id or self.session.current.session_id
        self._a2a_publish_context_sync(
            user_text=user_text,
            assistant_text=assistant_text,
            session_id=session_id,
        )

        # ── Tier 2: Intent Graph update ───────────────────────────────────────
        if hasattr(self, '_intent_graph') and self._intent_graph:
            try:
                self._intent_graph.ingest_turn(user_text)
            except Exception:
                pass

        # ── Tier 3: Commitment extraction ─────────────────────────────────────
        if hasattr(self, 'session') and user_text:
            try:
                commitments = extract_commitments(user_text, role="user", min_confidence=0.65)
                for c in commitments[:5]:
                    self._memory_executor.submit(
                        self.memory.add,
                        c.to_memory_text(),
                        session_id,
                        {"source": "commitment", "deadline_ts": c.deadline.isoformat() if c.deadline else None},
                    )
            except Exception:
                pass
        # ─────────────────────────────────────────────────────────────────────

        def _job() -> None:
            try:
                last_exc: Exception | None = None
                for attempt in range(2):
                    try:
                        self.memory.add(
                            text=f"User: {user_text}\nAssistant: {assistant_text}",
                            session_id=session_id,
                            metadata={"source": "conversation"},
                        )
                        self.memory.sync_pending(session_id)
                        last_exc = None
                        break
                    except Exception as exc:
                        last_exc = exc
                        if attempt == 0:
                            time.sleep(0.2)
                if last_exc is not None:
                    self.record_event("health", f"memory_write_failed:{last_exc}")
                    try:
                        import logging
                        logging.getLogger(__name__).warning("Memory write failed for session %s: %s", session_id, last_exc)
                    except Exception:
                        pass
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

    def _handle_goal_failure(self, goal: dict, result: Any) -> None:
        """Tier 4: Goal Outcome Learning — attempt LLM replanning on failure."""
        try:
            replan_count = int(goal.get("replan_count") or 0)
            steps = goal.get("steps") or []
            fail_index = int(getattr(result, 'next_index', 0))
            fail_step = steps[fail_index] if fail_index < len(steps) else {}
            reason = getattr(result, 'reason', 'unknown')

            if replan_count >= 2:
                # Second failure: escalate to human
                self._notify_telegram(
                    f"🛑 *Goal stuck:* {goal.get('goal', '')[:60]}\n"
                    f"Step {fail_index + 1} failed: `{fail_step.get('tool', '?')}` — {reason}\n"
                    "I've tried replanning once already. Want me to try a different approach?"
                )
                with self._goal_lock:
                    for g in self._goals:
                        if g.get("id") == goal.get("id"):
                            g["status"] = "requires_human"
                return

            # First failure: generate alternative step via LLM
            tool_hint = self.dispatcher.get_tool_schema_prompt() if hasattr(self.dispatcher, 'get_tool_schema_prompt') else ""
            prompt = (
                f"This goal step failed:\n{json.dumps(fail_step)}\n"
                f"Error: {reason}\n"
                f"Available tools:\n{tool_hint[:2000]}\n"
                "Suggest ONE alternative step as JSON: {\"tool\": \"...\", \"args\": {...}}"
            )
            raw = self.engine.ask(prompt=prompt, system="You are a goal replanning assistant.", history=[])
            new_step: dict = {}
            try:
                import re as _re
                m = _re.search(r'\{.*\}', raw, flags=_re.DOTALL)
                if m:
                    new_step = json.loads(m.group(0))
            except Exception:
                pass

            if not new_step or not new_step.get("tool"):
                return

            # Risk-check the new step
            from core.tools.dispatcher import ToolCall; check = guardrails.check(ToolCall(tool=new_step.get("tool", ""), args=new_step.get("args", {})))
            if getattr(check, 'score', 10) > 6:
                return  # too risky to auto-insert

            with self._goal_lock:
                for g in self._goals:
                    if g.get("id") == goal.get("id"):
                        new_steps = list(g.get("steps") or [])
                        new_steps.insert(fail_index, new_step)
                        g["steps"] = new_steps
                        g["status"] = "pending"
                        g["replan_count"] = replan_count + 1
                        self._persist_goals()
                        break
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("[goal_failure] replanning failed: %s", exc)

    def _auto_document_goal_outcome(self, goal: dict, result: Any, session_id: str | None = None) -> None:
        """Tier 4: Proactive Documentation — store a 2-sentence completion note."""
        try:
            steps = goal.get("steps") or []
            if len(steps) < 3:
                return  # only doc multi-step goals
            target_session_id = str(session_id or goal.get("session_id") or self.session.current.session_id)
            total_today = self.usage.total_tokens_today(session_id=target_session_id)
            budget_ok = total_today < int(settings.DAILY_TOKEN_ALERT_THRESHOLD * 0.8) if settings.DAILY_TOKEN_ALERT_THRESHOLD else True
            if not budget_ok:
                return
            step_summary = ", ".join(s.get("tool", "?") for s in steps[:5])
            prompt = (
                f"Summarize what was accomplished: {goal.get('goal', '')}\n"
                f"Steps taken: {step_summary}\n"
                "Write a 2-sentence note that future-you would want to know."
            )
            note = self.engine.ask(
                prompt=prompt,
                system="You are a concise technical note-taker.",
                history=[],
            ).strip()
            if note:
                self.memory.add(
                    note,
                    target_session_id,
                    {"source": "goal_outcome", "goal_id": str(goal.get("id", ""))},
                )
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("[auto_doc] documentation failed: %s", exc)

    def _track_usage(
        self,
        system_prompt: str,
        history: list[dict],
        user_text: str,
        assistant_text: str,
        *,
        day_anchor: date | None = None,
        session_id: str | None = None,
    ) -> None:
        input_tokens = estimate_tokens(system_prompt) + estimate_tokens(user_text)
        input_tokens += sum(estimate_tokens(str(m.get("content", ""))) for m in history)
        output_tokens = estimate_tokens(assistant_text)

        today = day_anchor or date.today()
        with self._usage_lock:
            session_id = session_id or self.session.current.session_id
            provider = self.engine.last_provider
            self.usage.add(provider, input_tokens, output_tokens, session_id=session_id, when=today)
            total = self.usage.total_tokens_for_day(today, session_id=session_id)
            if self._hard_cap_warning_day != today:
                self._hard_cap_warning_day = None
            if self._usage_alerted_day != today:
                self._usage_alerted_day = None
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
            if self._usage_alerted_day != today:
                if total >= settings.DAILY_TOKEN_ALERT_THRESHOLD:
                    print(f"\n[usage] Warning: daily token usage {total} exceeded threshold {settings.DAILY_TOKEN_ALERT_THRESHOLD}.")
                    self._usage_alerted_day = today

        # ── Tier 2: Behavior model recording ─────────────────────────────────
        if hasattr(self, '_behavior_model') and self._behavior_model:
            try:
                self._behavior_model.record_activity(
                    provider=provider,
                    session_id=session_id,
                )
            except Exception:
                pass
        # ─────────────────────────────────────────────────────────────────────

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
            if threading.current_thread() is not threading.main_thread():
                threading.Thread(
                    target=self._notify_telegram,
                    args=(f"High-risk confirmation required but request is non-interactive.\n{prompt}", 3),
                    daemon=True,
                ).start()
                return False
            if not sys.stdin or not sys.stdin.isatty():
                threading.Thread(
                    target=self._notify_telegram,
                    args=(f"High-risk confirmation required but no interactive stdin is available.\n{prompt}", 3),
                    daemon=True,
                ).start()
                return False
            answer = input(prompt).strip().lower()
            return answer in {"y", "yes", "confirm"}
        except Exception:
            return False

    def _is_hard_cap_active_today(self, today: date) -> bool:
        with self._usage_lock:
            if self._hard_cap_hit_date != today:
                self._hard_cap_hit = False
                self._hard_cap_hit_date = None
            return bool(self._hard_cap_hit and self._hard_cap_hit_date == today)

    def _network_online_cached(self) -> bool:
        now = time.monotonic()
        with self._network_online_lock:
            cached = self._network_online_cache
            cache_age = now - self._network_online_cache_at
            if cached is not None and cache_age < self._network_online_ttl_seconds:
                return cached
            if cached is not None and self._network_online_refresh_inflight:
                return cached
            if not self._network_online_refresh_inflight:
                self._network_online_refresh_inflight = True
                threading.Thread(target=self._refresh_network_online_state, daemon=True).start()
            if cached is not None:
                return cached
        # Cold-start path: return optimistic state while first probe runs in background.
        return True

    def _refresh_network_online_state(self) -> None:
        try:
            state = NetworkState.is_online(timeout=0.25)
            with self._network_online_lock:
                self._network_online_cache = state
                self._network_online_cache_at = time.monotonic()
        finally:
            with self._network_online_lock:
                self._network_online_refresh_inflight = False


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
