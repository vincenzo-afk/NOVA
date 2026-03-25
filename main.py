"""JARVIS entry point."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Generator

from pydantic import BaseModel, Field

from config.constants import DEFAULT_MEMORY_TOP_K, DEFAULT_SYSTEM_PROMPT
from config.settings import SettingsError, settings
from core.context.environment import snapshot_environment
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
from control.adb.tailscale import tailscale_ip_v4, tailscale_status
from control.browser import Browser
from interfaces.cli import run_cli
from rag.doc_store import DocumentStore
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


class JarvisApp:
    def __init__(self):
        settings.validate_startup(phase="phase1")

        self.dispatcher = Dispatcher()
        self.session = SessionManager(default_name=settings.DEFAULT_SESSION)
        self.trimmer = ContextTrimmer(max_raw_turns=10)
        self.health = HealthMonitor()
        self.memory = MemoryRouter(
            mem0=Mem0Client(api_key=settings.MEM0_API_KEY),
            local=LocalMemoryStore(),
        )
        self.docs = DocumentStore()
        self._browser: Browser | None = None
        self.adb = ADBClient()
        self.qr = QRPairing(adb_port=settings.ADB_PORT)
        self.omniparser = OmniParserServer(url=settings.OMNIPARSER_SERVER_URL)
        self.engine = LLMEngine(
            openai_base_url=settings.OPENAI_BASE_URL,
            openai_keys=settings.OPENAI_API_KEYS,
            ollama_base_url=settings.OLLAMA_BASE_URL,
            ollama_model=settings.OLLAMA_MODEL,
        )
        self.base_system_prompt = DEFAULT_SYSTEM_PROMPT
        self._register_builtin_tools()
        load_plugins(self.dispatcher)
        self._start_health_monitoring()

    def last_provider_label(self) -> str:
        return self.engine.last_provider

    def switch_session(self, name: str):
        return self.session.switch(name)

    def reset_context(self) -> None:
        self.session.reset_context()

    def status_text(self) -> str:
        return json.dumps(
            {
                "session": self.session.current.name,
                "session_id": self.session.current.session_id,
                "active_cloud_keys": self.engine.pool.active_count(),
                "memory_mode": "online" if self.memory.online else "offline",
                "provider_last": self.engine.last_provider,
                "tailscale_ip": tailscale_ip_v4(),
                "tailscale_status": tailscale_status(),
                "health": self.health.status_table(),
            },
            indent=2,
        )

    def _get_browser(self) -> Browser:
        if self._browser is None:
            self._browser = Browser(headless=True)
        return self._browser

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

    def _start_health_monitoring(self) -> None:
        self.health.register_subsystem("jarvis", lambda: True)
        self.health.register_subsystem("network", lambda: NetworkState.is_online())
        self.health.register_subsystem("memory_router", lambda: self.memory is not None)
        self.health.register_subsystem(
            "tailscale",
            lambda: tailscale_status() not in {"down"},
        )
        self.health.register_subsystem(
            "omniparser",
            check_fn=self.omniparser.is_running,
            restart_fn=self.omniparser.restart,
        )
        try:
            self.omniparser.ensure_running()
        except Exception:
            pass
        self.health.start(interval_seconds=60)

    def shutdown(self) -> None:
        self.health.stop()
        self._browser_close()
        try:
            self.omniparser.stop()
        except Exception:
            pass

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

    def _context_messages(self, user_text: str) -> tuple[str, list[dict], list[dict]]:
        session_id = self.session.current.session_id
        summary, recent = self.trimmer.trim(
            self.session.current.history,
            session_id=session_id,
        )
        memories = self.memory.search(user_text, session_id=session_id, top_k=DEFAULT_MEMORY_TOP_K)
        world_state = snapshot_environment()

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

        system_prompt = build_system_prompt(self.base_system_prompt, dispatcher=self.dispatcher)
        return system_prompt, [context_message, *recent], memories

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
        if re.match(r"^switch session\s+.+$", text):
            name = user_text.strip().split(maxsplit=2)[-1]
            state = self.switch_session(name)
            return f"Switched to {state.name} ({state.session_id})."
        return None

    def ask_stream(self, user_text: str) -> Generator[str, None, None]:
        command_response = self._apply_text_commands(user_text)
        if command_response:
            yield command_response
            return

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
        tool_call = self.dispatcher.try_parse_tool_call(assistant_text)
        if tool_call:
            result = self.dispatcher.execute(tool_call)
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


def main() -> int:
    try:
        app = JarvisApp()
    except SettingsError as exc:
        print(str(exc))
        return 1

    try:
        run_cli(app)
    finally:
        app.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
