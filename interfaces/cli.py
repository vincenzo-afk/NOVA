"""Rich-powered terminal interface for NOVA with streaming tokens.

Design:
  - Colour-coded status header on startup and after every /status call
  - Streaming token output — each token printed inline as it arrives
  - Full rich.Table for /health, /goals, /models
  - PBKDF2 PIN auth (preserved)
  - Bottom command-hint bar shown once after every response
  - All existing slash commands preserved + new /set, /profiles, /services
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from config.constants import AGENT_NAME, CLI_PIN_HASH_FILE, CLI_PIN_LEGACY_FILE, CLI_PIN_LOCK_FILE
from utils.events import format_event_log
from utils.goals import format_goal_list
from utils.health import format_health_table, summarize_health

HAS_RICH = True
try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.text import Text
    from rich.rule import Rule
    from rich.columns import Columns
    from rich import box as rich_box
except Exception:  # pragma: no cover
    HAS_RICH = False

    class Console:  # type: ignore[override]
        def print(self, *args, end="\n", **kwargs):
            _ = kwargs
            print(*args, end=end)

        def input(self, prompt: str) -> str:
            return input(prompt)

    class Table:  # type: ignore[override]
        def __init__(self, *a, **kw): pass
        def add_column(self, *a, **kw): pass
        def add_row(self, *a, **kw): pass

    class Panel:  # type: ignore[override]
        def __init__(self, *a, **kw): pass

    class Rule:  # type: ignore[override]
        def __init__(self, *a, **kw): pass


# ── Palette aliases ──────────────────────────────────────────────────────────
_C   = "cyan"
_G   = "green"
_Y   = "yellow"
_R   = "red"
_M   = "magenta"
_D   = "dim"
_B   = "bold"


def format_usage_message(title: str, summary: dict) -> str:
    if not summary:
        return f"{title}:\n(no usage yet)"
    lines = [f"{title}:"]
    for provider, data in summary.items():
        lines.append(
            f"{provider}: input={data.get('input_tokens', 0)} "
            f"output={data.get('output_tokens', 0)} total={data.get('total_tokens', 0)}"
        )
    return "\n".join(lines)


def _resolve_lock_file(path_value: str) -> Path:
    p = Path(path_value).expanduser()
    if p.is_absolute():
        return p
    return Path.home() / path_value.lstrip("./")


def _build_status_panel(agent) -> "Panel | str":
    """Build a rich Panel showing current NOVA status."""
    from core.llm.fallback import NetworkState
    try:
        session = agent.session.current
        session_name = session.name
        session_id = session.session_id
    except Exception:
        session_name, session_id = "—", "—"

    online = NetworkState.is_online()
    provider = str(getattr(agent, "last_provider_label", lambda: "unknown")())
    emotion = str(getattr(agent, "emotion_state", "neutral"))
    privacy = str(getattr(agent, "_get_session_privacy_mode", lambda *_: "full_cloud")())
    muted = bool(getattr(agent, "is_muted", lambda: False)())

    try:
        tokens_today = int(agent.usage.total_tokens_today(session_id=session_id))
    except Exception:
        tokens_today = 0

    try:
        from config.settings import settings
        cap = settings.DAILY_TOKEN_HARD_CAP or 500_000
    except Exception:
        cap = 500_000

    pct = min(100, int(tokens_today / cap * 100)) if cap else 0
    tok_color = _R if pct > 90 else _Y if pct > 70 else _G

    if not HAS_RICH:
        return (
            f"Session: {session_name} | Online: {online} | Provider: {provider} | "
            f"Emotion: {emotion} | Privacy: {privacy} | Muted: {muted} | "
            f"Tokens: {tokens_today:,}/{cap:,} ({pct}%)"
        )

    table = Table(box=rich_box.SIMPLE, show_header=False, padding=(0, 2))
    table.add_column("key", style=_D, width=14)
    table.add_column("value", style="white")
    table.add_row("Session", f"[{_C}]{session_name}[/{_C}] [dim]({session_id[:8]}…)[/dim]")
    table.add_row("Network", f"[{_G}]Online[/{_G}]" if online else f"[{_R}]Offline[/{_R}]")
    table.add_row("Provider", f"[{_M}]{provider}[/{_M}]")
    table.add_row("Emotion", emotion)
    table.add_row("Privacy", f"[{_Y}]{privacy}[/{_Y}]")
    table.add_row("Alerts", f"[{_Y}]Muted[/{_Y}]" if muted else f"[{_G}]Live[/{_G}]")
    table.add_row("Tokens", f"[{tok_color}]{tokens_today:,}[/{tok_color}] [dim]/ {cap:,} ({pct}%)[/dim]")

    return Panel(table, title=f"[{_C} bold]◈ NOVA Status[/{_C} bold]", border_style=_C, padding=(0, 1))


def _build_goals_table(agent) -> "Table | str":
    goals = agent.list_goals()
    raw = format_goal_list(goals)

    if not HAS_RICH:
        return raw

    table = Table(title="Goals", box=rich_box.ROUNDED, border_style=_C)
    table.add_column("ID", style="dim", width=12)
    table.add_column("Description", style="white", no_wrap=False)
    table.add_column("Status", width=12)
    table.add_column("Steps", justify="right", width=8)

    status_colors = {
        "pending": _Y, "running": _G, "done": "dim green",
        "failed": _R, "cancelled": "dim", "planning": _C,
        "blocked": _R,
    }

    if isinstance(goals, list):
        for g in goals:
            gid = str(g.get("id", ""))[:10]
            desc = str(g.get("description", ""))[:80]
            status = str(g.get("status", "unknown"))
            color = status_colors.get(status, "white")
            steps = str(len(g.get("steps", [])))
            table.add_row(gid, desc, f"[{color}]{status}[/{color}]", steps)
    else:
        table.add_row("—", raw[:80], "—", "—")

    return table


def _build_health_table(agent) -> "Table | str":
    try:
        items = agent.health.status_table()
        summary = summarize_health(items)
    except Exception as exc:
        return f"Health unavailable: {exc}"

    if not HAS_RICH:
        return f"Health summary: {summary}\n{format_health_table(items)}"

    table = Table(title=f"Health — {summary}", box=rich_box.ROUNDED, border_style=_G)
    table.add_column("Subsystem", style="white")
    table.add_column("Status", width=10)
    table.add_column("Last Checked", style="dim")

    for item in items:
        ok = item.get("ok", False)
        status_str = f"[{_G}]OK[/{_G}]" if ok else f"[{_R}]DOWN[/{_R}]"
        table.add_row(
            str(item.get("name", "?")),
            status_str,
            str(item.get("last_checked", "—")),
        )
    return table


def _build_models_table(rows: list[dict]) -> "Table | str":
    if not HAS_RICH:
        return "\n".join(
            f"{r.get('name') or r.get('model', 'unknown')} | {r.get('size', '')} | {r.get('modified_at', '')}"
            for r in rows
        )
    table = Table(title="Ollama Models", box=rich_box.ROUNDED, border_style=_M)
    table.add_column("Name", style="white")
    table.add_column("Size", justify="right", style="dim")
    table.add_column("Modified", style="dim")
    for r in rows:
        name = r.get("name") or r.get("model") or "unknown"
        size = str(r.get("size") or "—")
        mod = str(r.get("modified") or r.get("modified_at") or "—")
        table.add_row(name, size, mod)
    return table


def _hint_bar(console: "Console") -> None:
    """Print concise command hints."""
    if not HAS_RICH:
        return
    hints = (
        "[dim]/exit[/dim]  [dim]/reset[/dim]  [dim]/status[/dim]  [dim]/goals[/dim]  "
        "[dim]/health[/dim]  [dim]/usage[/dim]  [dim]/models[/dim]  [dim]/export[/dim]  "
        "[dim]/set KEY VALUE[/dim]  [dim]/profiles[/dim]  [dim]/services[/dim]  [dim]/help[/dim]"
    )
    console.print(Panel(hints, border_style="dim", padding=(0, 1)))


def _print_help(console: "Console") -> None:
    if not HAS_RICH:
        console.print("Commands: /exit /reset /status /goals /health /usage /usage week "
                      "/export [json|md] /session <name> /goal <desc> /resume_goal <id> "
                      "/cancel_goal <id> /mute /unmute /keys /privacy [mode] /models "
                      "/models pull <name> /models delete <name> /models benchmark "
                      "/mission list|add|enable|disable|run /a2a peers|inbox|send|delegate "
                      "/set KEY VALUE /profiles /services /theme [name]")
        return

    table = Table(box=rich_box.SIMPLE, show_header=True, border_style="dim")
    table.add_column("Command", style=_C, width=32)
    table.add_column("Description", style="white")

    commands = [
        ("/exit, /quit", "Exit NOVA CLI"),
        ("/reset", "Clear context history (keeps memory)"),
        ("/status", "Show live status panel"),
        ("/session <name>", "Switch to named session"),
        ("/goals", "List all goals in a table"),
        ("/goal <desc>", "Add a new goal"),
        ("/resume_goal <id>", "Resume a paused/failed goal"),
        ("/cancel_goal <id>", "Cancel a goal"),
        ("/health", "Show subsystem health table"),
        ("/usage [week]", "Show token usage"),
        ("/export [json|md]", "Export current session"),
        ("/mute / /unmute", "Toggle proactive alerts"),
        ("/keys", "Show configured API keys"),
        ("/privacy [mode]", "Get/set privacy mode"),
        ("/models [list|pull|delete|benchmark]", "Manage Ollama models"),
        ("/alerts", "Show recent event log"),
        ("/set KEY VALUE", "Live-mutate a setting (no restart needed)"),
        ("/profiles", "List saved settings profiles"),
        ("/services", "Check Ollama + OmniParser status"),
        ("/theme [name]", "Get/set theme lock"),
        ("/mission list|add|enable|disable|run", "Manage scheduled missions"),
        ("/a2a peers|inbox|send|delegate", "Agent-to-agent controls"),
    ]

    for cmd, desc in commands:
        table.add_row(cmd, desc)

    console.print(Panel(table, title=f"[{_C} bold]NOVA Commands[/{_C} bold]", border_style=_C))


def run_cli(agent) -> None:
    # ── PIN auth ──────────────────────────────────────────────────────────
    import getpass
    import hashlib
    import hmac

    def _verify_pin(entered: str, stored: str) -> bool:
        value = (stored or "").strip()
        if not value:
            return True
        if value.startswith("pbkdf2_sha256$"):
            try:
                _algo, iterations, salt, expected = value.split("$", 3)
                digest = hashlib.pbkdf2_hmac(
                    "sha256",
                    entered.encode("utf-8"),
                    salt.encode("utf-8"),
                    int(iterations),
                ).hex()
                return hmac.compare_digest(digest, expected)
            except Exception:
                return False
        return hmac.compare_digest(entered, value)

    pin_hash = ""
    pin_hash_file = Path(CLI_PIN_HASH_FILE)
    legacy_pin_file = Path(CLI_PIN_LEGACY_FILE)
    lock_file = _resolve_lock_file(CLI_PIN_LOCK_FILE)

    if pin_hash_file.exists():
        try:
            pin_hash = pin_hash_file.read_text(encoding="utf-8").strip()
        except Exception:
            pin_hash = ""
    elif legacy_pin_file.exists():
        try:
            pin_hash = legacy_pin_file.read_text(encoding="utf-8").strip()
        except Exception:
            pin_hash = ""

    if pin_hash:
        if lock_file.exists():
            try:
                unlock_at = float(lock_file.read_text(encoding="utf-8").strip() or "0")
                if time.time() < unlock_at:
                    wait = int(unlock_at - time.time())
                    print(f"Access temporarily locked. Try again in {wait}s.")
                    return
            except Exception:
                pass

        failed = 0
        while failed < 5:
            entered = getpass.getpass("Enter CLI_PIN to unlock NOVA: ")
            if _verify_pin(entered, pin_hash):
                lock_file.unlink(missing_ok=True)
                break
            failed += 1
            delay = min(30, 2 ** failed)
            time.sleep(delay)
        else:
            lock_file.parent.mkdir(parents=True, exist_ok=True)
            lock_file.write_text(str(time.time() + 300), encoding="utf-8")
            try:
                lock_file.chmod(0o600)
            except Exception:
                pass
            print("Access Denied. Too many failed attempts. Locked for 300 seconds.")
            return

    # ── Console init ──────────────────────────────────────────────────────
    console = Console()

    if HAS_RICH:
        console.print(Rule(f"[bold cyan]◈ NOVA  {AGENT_NAME} CLI[/bold cyan]", style="cyan"))
        console.print(_build_status_panel(agent))
    else:
        console.print(f"NOVA CLI — {AGENT_NAME}  |  Type /help for commands")

    _hint_bar(console)

    # ── Main REPL loop ────────────────────────────────────────────────────
    while True:
        prompt = "\n[bold cyan]You[/bold cyan] › " if HAS_RICH else "\nYou › "
        try:
            user_text = console.input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[yellow]Interrupted.[/yellow]" if HAS_RICH else "\nInterrupted.")
            return

        if not user_text:
            continue

        if len(user_text) > 50_000:
            console.print(
                f"[{_R}]Input too long ({len(user_text):,} chars). Shorten your message.[/{_R}]"
                if HAS_RICH else f"Input too long ({len(user_text):,} chars)."
            )
            continue

        # ── Exit ──────────────────────────────────────────────────────────
        if user_text in {"/exit", "/quit"}:
            console.print("[yellow]Goodbye.[/yellow]" if HAS_RICH else "Goodbye.")
            return

        # ── Reset context ─────────────────────────────────────────────────
        if user_text == "/reset":
            agent.reset_context()
            console.print("[yellow]Context reset. Memories kept.[/yellow]" if HAS_RICH else "Context reset.")
            continue

        # ── Status panel ──────────────────────────────────────────────────
        if user_text == "/status":
            console.print(_build_status_panel(agent))
            _hint_bar(console)
            continue

        # ── Help ──────────────────────────────────────────────────────────
        if user_text in {"/help", "/?"}:
            _print_help(console)
            continue

        # ── Session switch ────────────────────────────────────────────────
        if user_text.startswith("/session "):
            name = user_text.split(" ", 1)[1].strip()
            if name:
                state = agent.switch_session(name)
                console.print(
                    f"[{_C}]Switched to session:[/{_C}] {state.name} ({state.session_id})"
                    if HAS_RICH else f"Switched to: {state.name}"
                )
            continue

        # ── Keys ──────────────────────────────────────────────────────────
        if user_text == "/keys":
            try:
                from config.settings import settings
                from interfaces.key_manager import summarize_env_keys
                summary = summarize_env_keys(settings)
                if not summary:
                    console.print("No configured keys found.")
                else:
                    if HAS_RICH:
                        table = Table(box=rich_box.SIMPLE, show_header=True, border_style="dim")
                        table.add_column("Provider", style=_C)
                        table.add_column("Keys", style="dim")
                        for provider in sorted(summary.keys()):
                            table.add_row(provider, ", ".join(summary[provider]))
                        console.print(table)
                    else:
                        for p, keys in sorted(summary.items()):
                            console.print(f"{p}: {', '.join(keys)}")
            except Exception as exc:
                console.print(f"Key summary failed: {exc}")
            continue

        # ── Privacy ───────────────────────────────────────────────────────
        if user_text == "/privacy":
            mode = getattr(agent, "_get_session_privacy_mode", lambda *_: "full_cloud")()
            console.print(f"Privacy mode: [{_Y}]{mode}[/{_Y}]" if HAS_RICH else f"Privacy: {mode}")
            continue

        if user_text.startswith("/privacy "):
            mode_raw = user_text.split(" ", 1)[1].strip()
            setter = getattr(agent, "_set_session_privacy_mode", None)
            if callable(setter):
                selected = setter(mode_raw)
                console.print(f"Privacy mode → [{_Y}]{selected}[/{_Y}]" if HAS_RICH else f"Privacy → {selected}")
            else:
                console.print("Privacy mode controls unavailable.")
            continue

        # ── Usage ─────────────────────────────────────────────────────────
        if user_text == "/usage":
            sid = agent.session.current.session_id
            console.print(format_usage_message("Usage today", agent.usage.today_summary(session_id=sid)))
            continue

        if user_text == "/usage week":
            sid = agent.session.current.session_id
            console.print(format_usage_message("Usage this week", agent.usage.weekly_summary(session_id=sid)))
            continue

        # ── Health ────────────────────────────────────────────────────────
        if user_text == "/health":
            console.print(_build_health_table(agent))
            continue

        # ── Goals ─────────────────────────────────────────────────────────
        if user_text == "/goals":
            try:
                console.print(_build_goals_table(agent))
            except Exception as exc:
                console.print(f"Goals unavailable: {exc}")
            continue

        if user_text == "/alerts":
            try:
                console.print(format_event_log(agent.recent_events()))
            except Exception as exc:
                console.print(f"Alerts unavailable: {exc}")
            continue

        if user_text.startswith("/goal "):
            goal = user_text.split(" ", 1)[1].strip()
            if goal:
                console.print(agent.add_goal(goal))
            continue

        if user_text.startswith("/resume_goal "):
            gid = user_text.split(" ", 1)[1].strip()
            if gid:
                console.print(agent.resume_goal(gid))
            continue

        if user_text.startswith("/cancel_goal "):
            gid = user_text.split(" ", 1)[1].strip()
            if gid:
                console.print(agent.cancel_goal(gid))
            continue

        # ── Mute ──────────────────────────────────────────────────────────
        if user_text == "/mute":
            agent.set_muted(True)
            console.print("[yellow]Muted proactive alerts.[/yellow]" if HAS_RICH else "Muted.")
            continue

        if user_text == "/unmute":
            agent.set_muted(False)
            console.print("[green]Unmuted proactive alerts.[/green]" if HAS_RICH else "Unmuted.")
            continue

        # ── Export ────────────────────────────────────────────────────────
        if user_text.startswith("/export"):
            fmt = "md"
            parts = user_text.split(maxsplit=1)
            if len(parts) > 1 and parts[1].strip().lower() in {"json", "md", "markdown"}:
                v = parts[1].strip().lower()
                fmt = "json" if v == "json" else "md"
            console.print(f"Exporting as {fmt.upper()}…")
            session = agent.session.current
            with session._lock:
                history_snapshot = list(session.history)
            path = agent.export_session(fmt, history=history_snapshot)
            console.print(f"[green]Exported →[/green] {path}" if HAS_RICH else f"Exported → {path}")
            continue

        # ── Models ────────────────────────────────────────────────────────
        if user_text.startswith("/models"):
            try:
                from interfaces.model_manager import (
                    benchmark_providers, delete_ollama_model, list_ollama_models,
                    provider_key_snapshot, pull_ollama_model, recommend_provider,
                )
                cmd = user_text.strip()
                if cmd in {"/models", "/models list"}:
                    rows = list_ollama_models()
                    if not rows:
                        console.print("No Ollama models found.")
                    else:
                        console.print(_build_models_table(rows))
                elif cmd.startswith("/models pull "):
                    model = cmd.split(" ", 2)[2].strip()
                    if not model:
                        console.print("Usage: /models pull <model_name>")
                    else:
                        result = pull_ollama_model(model, on_output=lambda line: console.print(line))
                        console.print(result)
                elif cmd.startswith("/models delete "):
                    model = cmd.split(" ", 2)[2].strip()
                    console.print(delete_ollama_model(model) if model else "Usage: /models delete <name>")
                elif cmd in {"/models benchmark", "/models bench"}:
                    console.print(json.dumps(benchmark_providers(agent), ensure_ascii=False, indent=2))
                elif cmd in {"/models recommend", "/models auto"}:
                    console.print(json.dumps(recommend_provider(agent), ensure_ascii=False, indent=2))
                elif cmd in {"/models keys", "/models health"}:
                    console.print(json.dumps(provider_key_snapshot(agent), ensure_ascii=False, indent=2))
                else:
                    console.print("Usage: /models list|pull <name>|delete <name>|benchmark|recommend|keys")
            except Exception as exc:
                console.print(f"Model command failed: {exc}")
            continue

        # ── Theme ─────────────────────────────────────────────────────────
        if user_text == "/theme":
            current = str(getattr(agent, "get_theme_lock", lambda: "auto")())
            console.print(f"Theme: {current}")
            continue

        if user_text.startswith("/theme "):
            requested = user_text.split(" ", 1)[1].strip()
            selected = str(getattr(agent, "set_theme_lock", lambda x: x)(requested))
            console.print(f"Theme → '[{_Y}]{selected}[/{_Y}]'" if HAS_RICH else f"Theme → {selected}")
            continue

        # ── Missions ──────────────────────────────────────────────────────
        if user_text == "/mission list":
            try:
                console.print(json.dumps(agent._mission_list(), ensure_ascii=False, indent=2))
            except Exception as exc:
                console.print(f"Mission list failed: {exc}")
            continue

        if user_text.startswith("/mission enable "):
            console.print(agent._mission_enable(user_text.split(" ", 2)[2].strip()))
            continue

        if user_text.startswith("/mission disable "):
            console.print(agent._mission_disable(user_text.split(" ", 2)[2].strip()))
            continue

        if user_text.startswith("/mission run "):
            console.print(agent._mission_run_now(user_text.split(" ", 2)[2].strip()))
            continue

        if user_text.startswith("/mission add "):
            raw = user_text[len("/mission add "):].strip()
            parts = [p.strip() for p in raw.split("|")]
            if len(parts) != 3:
                console.print("Usage: /mission add <name> | <schedule> | <goal>")
            else:
                console.print(agent._mission_add(parts[0], parts[1], parts[2], True))
            continue

        # ── A2A ───────────────────────────────────────────────────────────
        if user_text == "/a2a peers":
            console.print(agent._a2a_peers())
            continue

        if user_text == "/a2a inbox":
            console.print(agent._a2a_inbox(50))
            continue

        if user_text.startswith("/a2a send "):
            raw = user_text[len("/a2a send "):].strip()
            parts = [p.strip() for p in raw.split("|")]
            if len(parts) != 3:
                console.print("Usage: /a2a send <to_agent> | <msg_type> | <json_payload>")
            else:
                try:
                    payload = json.loads(parts[2]) if parts[2] else {}
                    console.print(agent._a2a_send(parts[0], parts[1], payload))
                except Exception as exc:
                    console.print(f"Invalid JSON payload: {exc}")
            continue

        if user_text.startswith("/a2a delegate "):
            raw = user_text[len("/a2a delegate "):].strip()
            parts = [p.strip() for p in raw.split("|")]
            if len(parts) != 3:
                console.print("Usage: /a2a delegate <to_agent> | <tool_name> | <json_args>")
            else:
                try:
                    args = json.loads(parts[2]) if parts[2] else {}
                    fn = getattr(agent, "_a2a_delegate_tool", None)
                    console.print(fn(parts[0], parts[1], args, None) if callable(fn) else "A2A delegation unavailable.")
                except Exception as exc:
                    console.print(f"Invalid JSON args: {exc}")
            continue

        # ── Live settings mutation ─────────────────────────────────────────
        if user_text.startswith("/set "):
            parts = user_text.split(" ", 2)
            if len(parts) < 3:
                console.print("Usage: /set KEY VALUE")
                continue
            key, value = parts[1].strip(), parts[2].strip()
            try:
                from config.nova_settings_manager import apply_setting
                result = apply_setting(key, value)
                console.print(f"[{_G}]{result}[/{_G}]" if HAS_RICH else result)
            except Exception as exc:
                console.print(f"Failed to apply setting: {exc}")
            continue

        # ── Profiles ──────────────────────────────────────────────────────
        if user_text == "/profiles":
            try:
                from config.nova_settings_manager import list_profiles
                profiles = list_profiles()
                if not profiles:
                    console.print("No profiles saved yet. Use /save_profile <name> to create one.")
                else:
                    console.print(", ".join(profiles))
            except Exception as exc:
                console.print(f"Profiles unavailable: {exc}")
            continue

        if user_text.startswith("/save_profile "):
            name = user_text.split(" ", 1)[1].strip()
            try:
                from config.nova_settings_manager import save_profile
                console.print(save_profile(name))
            except Exception as exc:
                console.print(f"Save profile failed: {exc}")
            continue

        if user_text.startswith("/load_profile "):
            name = user_text.split(" ", 1)[1].strip()
            try:
                from config.nova_settings_manager import load_profile
                console.print(load_profile(name))
            except Exception as exc:
                console.print(f"Load profile failed: {exc}")
            continue

        # ── Services health ────────────────────────────────────────────────
        if user_text == "/services":
            def _probe() -> None:
                try:
                    from utils.service_health import check_all
                    from config.settings import settings as _s
                    result = check_all(_s.OLLAMA_BASE_URL, _s.OMNIPARSER_SERVER_URL)
                    if HAS_RICH:
                        table = Table(title="Service Health", box=rich_box.ROUNDED, border_style=_C)
                        table.add_column("Service", style="white")
                        table.add_column("Status", width=12)
                        table.add_column("Latency", width=12)
                        table.add_column("Detail", style="dim")
                        for svc, data in result.items():
                            if svc in {"overall", "checked_at"}:
                                continue
                            if not isinstance(data, dict):
                                continue
                            st = data.get("status", "—")
                            color = _G if st == "ok" else _R
                            lat = f"{data.get('latency_ms', '—')}ms"
                            detail = ", ".join(data.get("models", [])[:3]) or data.get("error", "—") or "—"
                            table.add_row(svc, f"[{color}]{st}[/{color}]", lat, detail)
                        console.print(table)
                    else:
                        for svc, data in result.items():
                            if isinstance(data, dict):
                                console.print(f"{svc}: {data.get('status', '?')}")
                except Exception as exc:
                    console.print(f"Services check failed: {exc}")
            import threading as _t
            _t.Thread(target=_probe, daemon=True).start()
            time.sleep(0.1)  # let the thread print before next prompt
            continue

        # ── Fallback: stream response ──────────────────────────────────────
        if HAS_RICH:
            console.print(f"\n[bold {_M}]{AGENT_NAME}[/bold {_M}] › ", end="")
        else:
            console.print(f"{AGENT_NAME} › ", end="")

        chunks = []
        for token in agent.ask_stream(user_text):
            chunks.append(token)
            console.print(token, end="")

        if not chunks:
            console.print("(no output)", end="")

        provider = agent.last_provider_label()
        if HAS_RICH:
            console.print(f"\n[dim][{provider}][/dim]")
        else:
            console.print(f"\n[{provider}]")

        _hint_bar(console)
