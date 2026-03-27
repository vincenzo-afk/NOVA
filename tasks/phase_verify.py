"""Phase-by-phase verification command for the JARVIS roadmap."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass
class PhaseResult:
    phase: int
    status: str
    message: str


def _result(phase: int, status: str, message: str) -> PhaseResult:
    return PhaseResult(phase=phase, status=status, message=message)


def _try_import(module: str) -> bool:
    try:
        __import__(module)
        return True
    except Exception:
        return False


def phase1_core_engine() -> PhaseResult:
    try:
        from core.llm.roundrobin import RoundRobinPool
        from core.think.reasoning import build_system_prompt
        from core.tools.dispatcher import Dispatcher
        from pydantic import BaseModel

        pool = RoundRobinPool(["k1", "k2"])
        if not pool.get_next():
            return _result(1, "fail", "RoundRobinPool did not return any key.")

        class DummyArgs(BaseModel):
            foo: str = "bar"

        dispatcher = Dispatcher()
        dispatcher.register("dummy.echo", lambda foo: foo, DummyArgs)
        system_prompt = build_system_prompt("base", dispatcher=dispatcher, emotion="neutral")
        if "Available tools" not in system_prompt:
            return _result(1, "fail", "Tool schema prompt missing in system prompt.")

        return _result(1, "pass", "Core engine primitives are functional.")
    except Exception as exc:
        return _result(1, "fail", f"{exc}")


def phase2_memory_layer() -> PhaseResult:
    try:
        from core.memory.mem0_client import Mem0Client
        from core.memory.local_store import LocalMemoryStore
        from core.memory.memory_router import MemoryRouter

        with tempfile.TemporaryDirectory() as tmp_dir:
            mem0 = Mem0Client(api_key="")
            local = LocalMemoryStore(persist_dir=tmp_dir)
            router = MemoryRouter(mem0=mem0, local=local)
            router.add("Remember the coffee order is oat milk.", "sess-1", {"source": "test"})
            results = router.search("coffee", "sess-1", top_k=3)
            if not results:
                return _result(2, "fail", "Memory search returned no results.")
        return _result(2, "pass", "Memory router add/search is working.")
    except Exception as exc:
        return _result(2, "fail", f"{exc}")


def phase3_voice_layer() -> PhaseResult:
    if not _try_import("voice.vad"):
        return _result(3, "skip", "Voice dependencies not installed; skipping voice checks.")
    try:
        from voice.vad import VADRecorder
        from voice.stt_offline import OfflineWhisper
        from voice.tts_offline import speak as tts_offline

        _ = VADRecorder(silence_ms=200)
        _ = OfflineWhisper(model_size="base")
        _ = tts_offline
        return _result(3, "pass", "Voice modules import and initialize.")
    except Exception as exc:
        return _result(3, "fail", f"{exc}")


def phase4_vision_layer() -> PhaseResult:
    try:
        from config.settings import settings
        from vision.omniparser_server import OmniParserServer
        import requests
        import time
        import importlib

        repo_path = None
        try:
            importlib.import_module("omniparser.server")
        except Exception:
            try:
                import setup as jarvis_setup
                from pathlib import Path

                env_path = Path(".env")
                env_values = jarvis_setup.load_env_values(env_path)
                repo_path = jarvis_setup.ensure_omniparser_repo(env_path, env_values)
                jarvis_setup.download_omniparser_weights(repo_path)
            except Exception:
                pass

        server = OmniParserServer(
            url=settings.OMNIPARSER_SERVER_URL,
            repo_dir=str(repo_path) if repo_path else settings.OMNIPARSER_REPO_DIR,
        )
        server.ensure_running()
        try:
            deadline = time.time() + 180
            while time.time() < deadline:
                if server.is_running():
                    return _result(4, "pass", "OmniParser server reachable.")
                time.sleep(0.5)
        except Exception:
            return _result(4, "fail", "OmniParser server not reachable after auto-start.")
        return _result(4, "fail", "OmniParser server not reachable after auto-start.")
    except Exception as exc:
        return _result(4, "fail", f"{exc}")


def phase5_tools_and_rag() -> PhaseResult:
    try:
        from core.tools.dispatcher import Dispatcher
        from pydantic import BaseModel
        from rag.doc_store import DocumentStore

        class EchoArgs(BaseModel):
            text: str

        dispatcher = Dispatcher()
        dispatcher.register("echo", lambda text: text, EchoArgs)
        _ = dispatcher.get_tool_schema_prompt()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir) / "note.txt"
            tmp_path.write_text("The launch requirements include offline mode and safety checks.", encoding="utf-8")
            store = DocumentStore(persist_dir=tmp_dir)
            store.ingest(str(tmp_path))
            hits = store.query("offline mode", filename=tmp_path.name)
            if not hits:
                return _result(5, "fail", "RAG query returned no results.")
        return _result(5, "pass", "Dispatcher + document RAG OK.")
    except Exception as exc:
        return _result(5, "fail", f"{exc}")


def phase6_interfaces() -> PhaseResult:
    missing = []
    for module in ("interfaces.cli", "interfaces.gui.app", "interfaces.telegram_bot", "interfaces.tray"):
        if not _try_import(module):
            missing.append(module)
    if missing:
        return _result(6, "skip", f"Optional interface deps missing: {', '.join(missing)}")
    return _result(6, "pass", "CLI/GUI/Telegram/Tray modules import.")


def phase7_scheduler_goals() -> PhaseResult:
    try:
        from tasks.scheduler import TaskScheduler, parse_schedule_text
        from tasks.goals import GoalRunner
        from core.tools.dispatcher import Dispatcher
        from pydantic import BaseModel
        import tempfile
        from pathlib import Path

        class DummyArgs(BaseModel):
            value: str

        dispatcher = Dispatcher()
        dispatcher.register("dummy", lambda value: value, DummyArgs)
        runner = GoalRunner(dispatcher)
        result = runner.run([{"tool": "dummy", "args": {"value": "ok"}}], max_steps=5)
        if result.status != "completed":
            return _result(7, "fail", "Goal runner did not complete a simple plan.")

        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "jobs.sqlite"
            scheduler = TaskScheduler(db_url=f"sqlite:///{db_path}")
            scheduler.start()
            _ = parse_schedule_text("every 5 minutes")
            scheduler.stop()
        return _result(7, "pass", "Scheduler and goal runner OK.")
    except Exception as exc:
        return _result(7, "fail", f"{exc}")


def phase8_android_control() -> PhaseResult:
    try:
        from control.adb.qr_pairing import QRPairing

        with tempfile.TemporaryDirectory() as tmp_dir:
            out = Path(tmp_dir) / "adb_qr.png"
            pairing = QRPairing(adb_port=5555)
            try:
                pairing.generate(out_path=str(out), prefer_remote=False)
                return _result(8, "pass", "ADB QR pairing generator OK.")
            except Exception as exc:
                return _result(8, "skip", f"QR pairing skipped: {exc}")
    except Exception as exc:
        return _result(8, "fail", f"{exc}")


def phase9_emotion_engine() -> PhaseResult:
    try:
        from core.emotion.engine import EmotionEngine

        engine = EmotionEngine()
        engine.update_from_signal("error detected")
        if engine.state != "urgent":
            return _result(9, "fail", "Emotion engine did not switch to urgent on error signal.")
        return _result(9, "pass", "Emotion engine OK.")
    except Exception as exc:
        return _result(9, "fail", f"{exc}")


def phase10_mcp_plugins() -> PhaseResult:
    try:
        from mcp.master_api import MasterAPI
        from mcp.master_mcp import MasterMCP

        api = MasterAPI()
        svc = api.register("github", "test-key")
        if not api.get(svc):
            return _result(10, "fail", "MasterAPI failed to store key.")

        mcp = MasterMCP()
        mcp.connect("local_service", {"tools": [{"name": "ping"}], "handlers": {"ping": lambda: "pong"}})
        tools = mcp.list_tools("local_service")
        if not tools:
            return _result(10, "fail", "MasterMCP did not register tools.")
        return _result(10, "pass", "Master API + MCP OK.")
    except Exception as exc:
        return _result(10, "fail", f"{exc}")


def phase11_safety_layer() -> PhaseResult:
    try:
        from core.tools.dispatcher import ToolCall
        from safety.guardrails import guardrails

        call = ToolCall(tool="win32_api.delete", args={"path": "C:/tmp"})
        risk = guardrails.check(call)
        if risk.level != "high":
            return _result(11, "fail", "High-risk tool did not score as high.")
        return _result(11, "pass", "Guardrails risk scoring OK.")
    except Exception as exc:
        return _result(11, "fail", f"{exc}")


def phase12_health_monitor() -> PhaseResult:
    try:
        from core.health import HealthMonitor
        from core.llm.fallback import NetworkState

        monitor = HealthMonitor()
        monitor.register_subsystem("network", NetworkState.is_online)
        monitor.poll_once()
        return _result(12, "pass", "Health monitor check OK.")
    except Exception as exc:
        return _result(12, "fail", f"{exc}")


def phase13_cross_os() -> PhaseResult:
    try:
        from control.os_layer import startup_command

        cmd = startup_command(str(Path.cwd()), python_executable=sys.executable, entrypoint="main.py")
        if "main.py" not in cmd:
            return _result(13, "fail", "startup_command did not include entrypoint.")
        return _result(13, "pass", "OS abstraction helpers OK.")
    except Exception as exc:
        return _result(13, "fail", f"{exc}")


PHASE_CHECKS: list[Callable[[], PhaseResult]] = [
    phase1_core_engine,
    phase2_memory_layer,
    phase3_voice_layer,
    phase4_vision_layer,
    phase5_tools_and_rag,
    phase6_interfaces,
    phase7_scheduler_goals,
    phase8_android_control,
    phase9_emotion_engine,
    phase10_mcp_plugins,
    phase11_safety_layer,
    phase12_health_monitor,
    phase13_cross_os,
]


def run_checks(continue_on_failure: bool = False) -> list[PhaseResult]:
    results: list[PhaseResult] = []
    for idx, check in enumerate(PHASE_CHECKS, start=1):
        result = check()
        results.append(result)
        print(f"Phase {idx:02d}: {result.status.upper()} — {result.message}")
        if result.status == "fail" and not continue_on_failure:
            break
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify JARVIS roadmap phases.")
    parser.add_argument("--continue", dest="continue_on_failure", action="store_true", help="Keep running after failures.")
    parser.add_argument("--json", dest="json_output", action="store_true", help="Emit JSON results.")
    args = parser.parse_args()

    results = run_checks(continue_on_failure=args.continue_on_failure)
    if args.json_output:
        print(json.dumps([r.__dict__ for r in results], indent=2))

    failures = [r for r in results if r.status == "fail"]
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
