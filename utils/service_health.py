"""Service health monitor for Ollama, OmniParser, and system probes.

Provides:
  - check_ollama()        → dict with status, latency, models list
  - check_omniparser()    → dict with status, latency
  - check_all()           → combined dict of all service states
  - start_ollama_serve()  → attempt to launch `ollama serve` if not running
  - ServiceHealthMonitor  → periodic background checker with callbacks
  - FEATURE_AUDIT         → 50+ wired features with source refs and GUI control types
"""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from typing import Any, Callable


# ---------------------------------------------------------------------------
# Individual service probes
# ---------------------------------------------------------------------------

def check_ollama(base_url: str = "http://localhost:11434", timeout: float = 5.0) -> dict[str, Any]:
    """
    Probe the Ollama REST API.

    Returns::

        {
          "status": "ok" | "degraded" | "down",
          "latency_ms": float | None,
          "models": [...],
          "error": str | None,
        }
    """
    import requests  # type: ignore[import]
    base = base_url.rstrip("/")
    t0 = time.monotonic()
    # Try /api/tags first (preferred), fall back to /v1/models for OpenAI-compat wrappers
    for path in ("/api/tags", "/v1/models", "/health"):
        try:
            resp = requests.get(f"{base}{path}", timeout=timeout)
            latency_ms = round((time.monotonic() - t0) * 1000, 1)
            if resp.ok:
                models: list[str] = []
                try:
                    body = resp.json()
                    if "models" in body:
                        models = [m.get("name") or m.get("id", "") for m in body["models"]]
                    elif "data" in body:
                        models = [m.get("id", "") for m in body["data"]]
                except Exception:
                    pass
                return {"status": "ok", "latency_ms": latency_ms, "models": models, "error": None}
        except Exception as exc:
            last_exc = str(exc)
            continue
    latency_ms = round((time.monotonic() - t0) * 1000, 1)
    return {
        "status": "down",
        "latency_ms": latency_ms,
        "models": [],
        "error": locals().get("last_exc", "unreachable"),
    }


def check_omniparser(base_url: str = "http://localhost:8000", timeout: float = 5.0) -> dict[str, Any]:
    """
    Probe the OmniParser FastAPI server.

    Returns::

        {
          "status": "ok" | "degraded" | "down",
          "latency_ms": float | None,
          "error": str | None,
        }
    """
    import requests  # type: ignore[import]
    base = base_url.rstrip("/")
    t0 = time.monotonic()
    for path in ("/health", "/", "/docs"):
        try:
            resp = requests.get(f"{base}{path}", timeout=timeout)
            latency_ms = round((time.monotonic() - t0) * 1000, 1)
            if resp.ok:
                return {"status": "ok", "latency_ms": latency_ms, "error": None}
        except Exception as exc:
            last_exc = str(exc)
            continue
    latency_ms = round((time.monotonic() - t0) * 1000, 1)
    return {
        "status": "down",
        "latency_ms": latency_ms,
        "error": locals().get("last_exc", "unreachable"),
    }


def check_all(ollama_url: str = "http://localhost:11434",
              omniparser_url: str = "http://localhost:8000") -> dict[str, Any]:
    """Run all probes and return combined results."""
    ollama = check_ollama(ollama_url)
    omniparser = check_omniparser(omniparser_url)
    overall = "ok"
    if ollama["status"] == "down":
        overall = "degraded"
    if ollama["status"] == "down" and omniparser["status"] == "down":
        overall = "critical"
    return {
        "overall": overall,
        "ollama": ollama,
        "omniparser": omniparser,
        "checked_at": time.time(),
    }


# ---------------------------------------------------------------------------
# Service launcher
# ---------------------------------------------------------------------------

def start_ollama_serve() -> str:
    """
    Attempt to launch `ollama serve` if it is not already running.
    Returns a status string.
    """
    # Check if it's already running
    try:
        result = subprocess.run(
            ["pgrep", "-f", "ollama serve"],
            capture_output=True,
        )
        if result.returncode == 0:
            return "Ollama is already running"
    except FileNotFoundError:
        pass  # pgrep not available (Windows) — try anyway

    # Check ollama binary exists
    import shutil
    if not shutil.which("ollama"):
        return "ollama binary not found in PATH"

    try:
        subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        # Give it a moment to start
        for _ in range(10):
            time.sleep(0.5)
            probe = check_ollama()
            if probe["status"] == "ok":
                return "Ollama started successfully"
        return "Ollama launched but not yet responding"
    except Exception as exc:
        return f"Failed to start Ollama: {exc}"


def ensure_ollama_running(base_url: str = "http://localhost:11434") -> str:
    """Check Ollama and auto-start if needed. Called from main.py boot."""
    probe = check_ollama(base_url)
    if probe["status"] == "ok":
        return "ok"
    return start_ollama_serve()


# ---------------------------------------------------------------------------
# Background periodic health monitor
# ---------------------------------------------------------------------------

class ServiceHealthMonitor:
    """
    Runs health checks in a daemon thread on a configurable interval.
    Calls *on_update* with the latest ``check_all()`` result whenever it runs.

    Usage::

        monitor = ServiceHealthMonitor(interval=30, on_update=my_callback)
        monitor.start()
        # …
        monitor.stop()
    """

    def __init__(
        self,
        interval: float = 30.0,
        on_update: Callable[[dict[str, Any]], None] | None = None,
        ollama_url: str = "http://localhost:11434",
        omniparser_url: str = "http://localhost:8000",
    ) -> None:
        self.interval = interval
        self.on_update = on_update
        self.ollama_url = ollama_url
        self.omniparser_url = omniparser_url
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_result: dict[str, Any] = {}
        self._lock = threading.Lock()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="ServiceHealthMonitor")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5.0)
            self._thread = None

    def last_result(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._last_result)

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                result = check_all(self.ollama_url, self.omniparser_url)
                with self._lock:
                    self._last_result = result
                if self.on_update:
                    try:
                        self.on_update(result)
                    except Exception:
                        pass
            except Exception:
                pass
            self._stop_event.wait(timeout=self.interval)


# ---------------------------------------------------------------------------
# Feature audit registry
# ---------------------------------------------------------------------------

FEATURE_AUDIT: list[dict[str, str]] = [
    # ── Core chat ─────────────────────────────────────────────────────────────
    {"feature": "Streaming chat", "file": "main.py", "fn": "chat()", "gui": "QTextEdit stream"},
    {"feature": "Session switch", "file": "main.py", "fn": "switch_session()", "gui": "QLineEdit + Button"},
    {"feature": "Context reset", "file": "main.py", "fn": "reset_context()", "gui": "Button"},
    {"feature": "Emotion display", "file": "core/emotion/engine.py", "fn": "EmotionEngine.state", "gui": "Status label"},
    {"feature": "Provider display", "file": "main.py", "fn": "last_provider_label()", "gui": "Status label"},
    {"feature": "Daily token counter", "file": "utils/usage_tracker.py", "fn": "total_tokens_today()", "gui": "Progress bar"},
    {"feature": "Privacy mode toggle", "file": "main.py", "fn": "_set_session_privacy_mode()", "gui": "QComboBox"},
    {"feature": "Mute toggle", "file": "main.py", "fn": "set_muted()", "gui": "Toggle button"},

    # ── Voice ─────────────────────────────────────────────────────────────────
    {"feature": "STT (Whisper)", "file": "voice/stt.py", "fn": "transcribe()", "gui": "Mic button"},
    {"feature": "TTS (cloud Gemini)", "file": "main.py", "fn": "_speak()", "gui": "Voice wave visualiser"},
    {"feature": "TTS (offline pyttsx3)", "file": "voice/tts_offline.py", "fn": "speak()", "gui": "Voice wave visualiser"},
    {"feature": "Wake-word listen", "file": "voice/wakeword.py", "fn": "WakeWordListener", "gui": "Porcupine status dot"},
    {"feature": "Barge-in (interrupt)", "file": "main.py", "fn": "_barge_in_event", "gui": "Hotkey indicator"},
    {"feature": "Ambient monitor", "file": "voice/ambient_listener.py", "fn": "AmbientListener", "gui": "Ambient status dot"},

    # ── Memory ────────────────────────────────────────────────────────────────
    {"feature": "Local ChromaDB store", "file": "core/memory/local_store.py", "fn": "LocalMemoryStore", "gui": "Memory count badge"},
    {"feature": "Cloud mem0 sync", "file": "core/memory/mem0_client.py", "fn": "Mem0Client", "gui": "Sync status dot"},
    {"feature": "Session export", "file": "utils/exporter.py", "fn": "export_json/export_markdown", "gui": "Export button + format picker"},
    {"feature": "ChromaDB backup", "file": "core/memory/backup.py", "fn": "_backup_chromadb()", "gui": "Backup status in Debug"},
    {"feature": "Intent graph", "file": "core/memory/intent_graph.py", "fn": "IntentGraph", "gui": "Graph view (Debug tab)"},

    # ── Goals & autonomy ──────────────────────────────────────────────────────
    {"feature": "Add goal", "file": "main.py", "fn": "_add_goal()", "gui": "QLineEdit + Button"},
    {"feature": "Cancel goal", "file": "main.py", "fn": "cancel_goal()", "gui": "Button in goal list"},
    {"feature": "Resume goal", "file": "main.py", "fn": "resume_goal()", "gui": "Button in goal list"},
    {"feature": "List goals", "file": "main.py", "fn": "list_goals()", "gui": "QPlainTextEdit / Table"},
    {"feature": "Autonomy loop toggle", "file": "main.py", "fn": "_start_autonomy_loop()", "gui": "Toggle in Autonomy tab"},
    {"feature": "Goal step visualiser", "file": "tasks/goals.py", "fn": "GoalRunner.run()", "gui": "Step progress bar"},
    {"feature": "Goal templates", "file": "core/goals/template_library.py", "fn": "GoalTemplateLibrary", "gui": "Template picker (Autonomy)"},
    {"feature": "Proactive goal engine", "file": "core/goals/proactive_goal_engine.py", "fn": "ProactiveGoalEngine", "gui": "Active goals badge"},

    # ── Safety ────────────────────────────────────────────────────────────────
    {"feature": "Risk scoring", "file": "safety/guardrails.py", "fn": "Guardrails.check()", "gui": "Risk badge on step"},
    {"feature": "Emergency stop", "file": "safety/guardrails.py", "fn": "is_emergency_stopped()", "gui": "Big red STOP button"},
    {"feature": "VirusTotal scan", "file": "safety/virus_scanner.py", "fn": "VirusScanner", "gui": "Scan status in Debug"},
    {"feature": "Plugin sandbox", "file": "core/plugin_loader.py", "fn": "load_plugins()", "gui": "Plugin list (Settings)"},

    # ── Integrations ─────────────────────────────────────────────────────────
    {"feature": "Telegram notify", "file": "utils/notifier.py", "fn": "send_telegram_text()", "gui": "Telegram status dot"},
    {"feature": "ADB / phone control", "file": "control/adb/adb_client.py", "fn": "ADBClient", "gui": "ADB status dot"},
    {"feature": "Browser automation", "file": "control/browser.py", "fn": "Browser", "gui": "Browser status dot"},
    {"feature": "Win32 API", "file": "control/win32_api.py", "fn": "execute()", "gui": "OS control status"},
    {"feature": "Scheduler", "file": "tasks/scheduler.py", "fn": "TaskScheduler", "gui": "Missions list (Autonomy)"},
    {"feature": "Mission manager", "file": "tasks/missions.py", "fn": "MissionManager", "gui": "Add/remove missions (Autonomy)"},

    # ── Proactive intelligence ────────────────────────────────────────────────
    {"feature": "Screen watcher", "file": "vision/watcher.py", "fn": "ScreenWatcher", "gui": "Watcher toggle (Settings)"},
    {"feature": "Phone watcher", "file": "control/adb/watcher.py", "fn": "PhoneWatcher", "gui": "Phone watcher toggle"},
    {"feature": "Nudge engine", "file": "core/think/nudge_engine.py", "fn": "NudgeEngine", "gui": "Nudge history (Debug)"},
    {"feature": "Behaviour model", "file": "utils/behavior_model.py", "fn": "BehaviorModel", "gui": "Insights tab"},
    {"feature": "Pattern shortcuts", "file": "tasks/pattern_shortcuts.py", "fn": "PatternShortcutCompiler", "gui": "Shortcuts panel (Autonomy)"},
    {"feature": "Insight extractor", "file": "utils/insight_extractor.py", "fn": "InsightExtractor", "gui": "Weekly insights view"},
    {"feature": "Prompt evolver", "file": "core/think/prompt_evolver.py", "fn": "PromptEvolver", "gui": "Prompt version history"},
    {"feature": "Self-evaluator", "file": "core/think/self_evaluator.py", "fn": "SelfEvaluator", "gui": "Quality score badge"},
    {"feature": "FS watcher", "file": "core/context/fs_watcher.py", "fn": "NOVAFSWatcher", "gui": "FS event log (Debug)"},

    # ── Vision ────────────────────────────────────────────────────────────────
    {"feature": "OmniParser UI parse", "file": "vision/omniparser.py", "fn": "OmniParserClient.ui_elements()", "gui": "OmniParser status (Debug)"},
    {"feature": "OmniParser server mgmt", "file": "vision/omniparser_server.py", "fn": "OmniParserServer", "gui": "Start/stop button (Debug)"},
    {"feature": "Gemini Vision", "file": "vision/gemini_vision.py", "fn": "analyze_image()", "gui": "Image attach button (Chat)"},
    {"feature": "Screen capture", "file": "vision/capture.py", "fn": "capture_screen()", "gui": "Screenshot button (Debug)"},

    # ── A2A ───────────────────────────────────────────────────────────────────
    {"feature": "Peer registry", "file": "core/a2a/peer_registry.py", "fn": "PeerRegistry", "gui": "Peers list (Debug)"},
    {"feature": "Shared memory bus", "file": "core/a2a/shared_memory_bus.py", "fn": "SharedMemoryBus", "gui": "Bus message log (Debug)"},

    # ── Settings ──────────────────────────────────────────────────────────────
    {"feature": "Live settings mutation", "file": "config/nova_settings_manager.py", "fn": "apply_setting()", "gui": "SettingsPage fields"},
    {"feature": "Profile save/load", "file": "config/nova_settings_manager.py", "fn": "save_profile()/load_profile()", "gui": "Profile picker (Settings)"},
    {"feature": "BYOK key manager", "file": "interfaces/key_manager.py", "fn": "EncryptedKeyStore", "gui": "Key Manager dialog"},
    {"feature": "Model manager", "file": "interfaces/model_manager.py", "fn": "list_ollama_models()", "gui": "Model Manager dialog"},
]

# Top 10 priority wiring items (not yet fully surfaced in GUI as of Phase 14)
PRIORITY_WIRING: list[str] = [
    "Emergency stop — needs a prominent always-visible STOP button in all tabs",
    "Daily token usage — progress bar with colour coding in status bar",
    "Autonomy loop enable/disable toggle — must be live, not restart-required",
    "OmniParser health + auto-start — Debug tab with green/red dot + Start button",
    "Ollama health + model list — Debug tab live refresh",
    "Privacy mode switcher — per-session QComboBox in Settings or status bar",
    "Goal step visualiser — real-time step progress during execution",
    "STT mic button — push-to-talk with waveform animation",
    "Profile load/save — dropdown in Settings with quick-apply",
    "Screen watcher enable/interval — live toggles without restart",
]
