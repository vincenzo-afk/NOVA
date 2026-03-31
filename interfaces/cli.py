"""Rich terminal interface with streamed tokens."""

from __future__ import annotations

import time
from pathlib import Path

from config.constants import AGENT_NAME, CLI_PIN_HASH_FILE, CLI_PIN_LEGACY_FILE, CLI_PIN_LOCK_FILE
from utils.events import format_event_log
from utils.goals import format_goal_list
from utils.health import format_health_table, summarize_health

HAS_RICH = True
try:
    from rich.console import Console
except Exception:  # pragma: no cover
    HAS_RICH = False

    class Console:  # type: ignore[override]
        def print(self, *args, end="\n", **kwargs):
            _ = kwargs
            print(*args, end=end)

        def input(self, prompt: str) -> str:
            return input(prompt)


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


def run_cli(agent) -> None:
    # Simple CLI authentication via local file (avoids leaking secret via env/process list).
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
        # legacy plaintext support
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
                try:
                    lock_file.unlink(missing_ok=True)
                except Exception:
                    pass
                break
            failed += 1
            try:
                lock_file.parent.mkdir(parents=True, exist_ok=True)
                lock_until = time.time() + min(300, 2 ** failed)
                lock_file.write_text(str(lock_until), encoding="utf-8")
                try:
                    lock_file.chmod(0o600)
                except Exception:
                    pass
            except Exception:
                pass
            delay = min(30, 2 ** failed)
            time.sleep(delay)
        else:
            lock_file.parent.mkdir(parents=True, exist_ok=True)
            lock_file.write_text(str(time.time() + 300), encoding="utf-8")
            try:
                lock_file.chmod(0o600)
            except Exception:
                pass
            print("Access Denied. Too many failed attempts.")
            return

    console = Console()
    banner = "[bold cyan]NOVA CLI[/bold cyan]  Type /exit to quit" if HAS_RICH else "NOVA CLI  Type /exit to quit"
    console.print(banner)

    while True:
        prompt = "\n[bold green]You[/bold green] > " if HAS_RICH else "\nYou > "
        user_text = console.input(prompt).strip()
        if not user_text:
            continue
        # Fix 6.9: Guard against excessively long input
        if len(user_text) > 50_000:
            msg = (
                "[red]Input too long ({:,} chars). Please shorten your message.[/red]".format(len(user_text))
                if HAS_RICH
                else "Input too long ({:,} chars). Please shorten your message.".format(len(user_text))
            )
            console.print(msg)
            continue
        if user_text in {"/exit", "/quit"}:
            console.print("[yellow]Goodbye.[/yellow]" if HAS_RICH else "Goodbye.")
            return
        if user_text == "/reset":
            agent.reset_context()
            msg = "[yellow]Context reset. Memories kept.[/yellow]" if HAS_RICH else "Context reset. Memories kept."
            console.print(msg)
            continue
        if user_text.startswith("/session "):
            name = user_text.split(" ", 1)[1].strip()
            if name:
                state = agent.switch_session(name)
                msg = (
                    f"[cyan]Switched to session:[/cyan] {state.name} ({state.session_id})"
                    if HAS_RICH
                    else f"Switched to session: {state.name} ({state.session_id})"
                )
                console.print(msg)
                continue
        if user_text == "/status":
            console.print(agent.status_text())
            continue
        if user_text == "/usage":
            session_id = agent.session.current.session_id
            console.print(format_usage_message("Usage today", agent.usage.today_summary(session_id=session_id)))
            continue
        if user_text == "/usage week":
            session_id = agent.session.current.session_id
            console.print(format_usage_message("Usage this week", agent.usage.weekly_summary(session_id=session_id)))
            continue
        if user_text == "/health":
            try:
                items = agent.health.status_table()
                console.print(f"Health summary: {summarize_health(items)}")
                console.print(format_health_table(items))
            except Exception as exc:
                console.print(f"Health unavailable: {exc}")
            continue
        if user_text == "/goals":
            try:
                console.print(format_goal_list(agent.list_goals()))
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
            goal_id = user_text.split(" ", 1)[1].strip()
            if goal_id:
                console.print(agent.resume_goal(goal_id))
            continue
        if user_text.startswith("/cancel_goal "):
            goal_id = user_text.split(" ", 1)[1].strip()
            if goal_id:
                console.print(agent.cancel_goal(goal_id))
            continue
        if user_text == "/mute":
            agent.set_muted(True)
            console.print("Muted proactive alerts/notifications.")
            continue
        if user_text == "/unmute":
            agent.set_muted(False)
            console.print("Unmuted proactive alerts/notifications.")
            continue
        if user_text.startswith("/export"):
            fmt = "md"
            parts = user_text.split(maxsplit=1)
            if len(parts) > 1 and parts[1].strip().lower() in {"json", "md", "markdown"}:
                v = parts[1].strip().lower()
                fmt = "json" if v == "json" else "md"
            console.print(f"Exporting as {fmt.upper()}...")
            path = agent.export_session(fmt)
            console.print(f"Exported session -> {path}")
            continue

        prefix = f"[bold magenta]{AGENT_NAME}[/bold magenta] > " if HAS_RICH else f"{AGENT_NAME} > "
        console.print(prefix, end="")
        chunks = []
        for token in agent.ask_stream(user_text):
            chunks.append(token)
            console.print(token, end="")

        if not chunks:
            console.print("(no output)", end="")

        provider_msg = f"\n[dim][{agent.last_provider_label()}][/dim]" if HAS_RICH else f"\n[{agent.last_provider_label()}]"
        console.print(provider_msg)
