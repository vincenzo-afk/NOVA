"""Rich terminal interface with streamed tokens."""

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
            delay = min(30, 2 ** failed)
            time.sleep(delay)
        else:
            lock_file.parent.mkdir(parents=True, exist_ok=True)
            lock_seconds = 300
            lock_file.write_text(str(time.time() + lock_seconds), encoding="utf-8")
            try:
                lock_file.chmod(0o600)
            except Exception:
                pass
            print(f"Access Denied. Too many failed attempts. Locked for {lock_seconds} seconds.")
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
        if user_text == "/keys":
            try:
                from config.settings import settings
                from interfaces.key_manager import summarize_env_keys

                summary = summarize_env_keys(settings)
                if not summary:
                    console.print("No configured keys found.")
                else:
                    for provider in sorted(summary.keys()):
                        console.print(f"{provider}: {', '.join(summary[provider])}")
            except Exception as exc:
                console.print(f"Key summary failed: {exc}")
            continue
        if user_text == "/privacy":
            mode = getattr(agent, "_get_session_privacy_mode", lambda *_: "full_cloud")()
            console.print(f"Current session privacy mode: {mode}")
            continue
        if user_text.startswith("/privacy "):
            mode_raw = user_text.split(" ", 1)[1].strip()
            setter = getattr(agent, "_set_session_privacy_mode", None)
            if callable(setter):
                selected = setter(mode_raw)
                console.print(f"Session privacy mode set to: {selected}")
            else:
                console.print("Privacy mode controls unavailable.")
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
            session = agent.session.current
            with session._lock:
                history_snapshot = list(session.history)
            path = agent.export_session(fmt, history=history_snapshot)
            console.print(f"Exported session -> {path}")
            continue
        if user_text.startswith("/models"):
            try:
                from interfaces.model_manager import (
                    benchmark_providers,
                    delete_ollama_model,
                    list_ollama_models,
                    provider_key_snapshot,
                    pull_ollama_model,
                    recommend_provider,
                )

                cmd = user_text.strip()
                if cmd in {"/models", "/models list"}:
                    rows = list_ollama_models()
                    if not rows:
                        console.print("No Ollama models found.")
                    else:
                        for item in rows:
                            name = item.get("name") or item.get("model") or "unknown"
                            size = item.get("size") or ""
                            modified = item.get("modified") or item.get("modified_at") or ""
                            console.print(f"{name} | {size} | {modified}")
                elif cmd.startswith("/models pull "):
                    model = cmd.split(" ", 2)[2].strip()
                    if not model:
                        console.print("Usage: /models pull <model_name>")
                    else:
                        result = pull_ollama_model(model, on_output=lambda line: console.print(line))
                        console.print(result)
                elif cmd.startswith("/models delete "):
                    model = cmd.split(" ", 2)[2].strip()
                    if not model:
                        console.print("Usage: /models delete <model_name>")
                    else:
                        console.print(delete_ollama_model(model))
                elif cmd in {"/models benchmark", "/models bench"}:
                    rows = benchmark_providers(agent)
                    console.print(json.dumps(rows, ensure_ascii=False, indent=2))
                elif cmd in {"/models recommend", "/models auto"}:
                    rec = recommend_provider(agent)
                    console.print(json.dumps(rec, ensure_ascii=False, indent=2))
                elif cmd in {"/models keys", "/models health"}:
                    snap = provider_key_snapshot(agent)
                    console.print(json.dumps(snap, ensure_ascii=False, indent=2))
                else:
                    console.print(
                        "Usage: /models list|pull <name>|delete <name>|benchmark|recommend|keys"
                    )
            except Exception as exc:
                console.print(f"Model command failed: {exc}")
            continue
        if user_text == "/theme":
            current = str(getattr(agent, "get_theme_lock", lambda: "auto")())
            console.print(f"Theme mode: {current}")
            continue
        if user_text.startswith("/theme "):
            requested = user_text.split(" ", 1)[1].strip()
            selected = str(getattr(agent, "set_theme_lock", lambda x: x)(requested))
            if selected == "auto":
                console.print("Theme auto-switch enabled.")
            else:
                console.print(f"Theme locked to '{selected}'.")
            continue
        if user_text == "/mission list":
            try:
                console.print(agent._mission_list())
            except Exception as exc:
                console.print(f"Mission list failed: {exc}")
            continue
        if user_text.startswith("/mission enable "):
            name = user_text.split(" ", 2)[2].strip()
            console.print(agent._mission_enable(name))
            continue
        if user_text.startswith("/mission disable "):
            name = user_text.split(" ", 2)[2].strip()
            console.print(agent._mission_disable(name))
            continue
        if user_text.startswith("/mission run "):
            name = user_text.split(" ", 2)[2].strip()
            console.print(agent._mission_run_now(name))
            continue
        if user_text.startswith("/mission add "):
            # /mission add <name> | <schedule> | <goal>
            raw = user_text[len("/mission add ") :].strip()
            parts = [p.strip() for p in raw.split("|")]
            if len(parts) != 3:
                console.print("Usage: /mission add <name> | <schedule> | <goal>")
            else:
                console.print(agent._mission_add(parts[0], parts[1], parts[2], True))
            continue
        if user_text == "/a2a peers":
            console.print(agent._a2a_peers())
            continue
        if user_text == "/a2a inbox":
            console.print(agent._a2a_inbox(50))
            continue
        if user_text.startswith("/a2a send "):
            raw = user_text[len("/a2a send ") :].strip()
            parts = [p.strip() for p in raw.split("|")]
            if len(parts) != 3:
                console.print("Usage: /a2a send <to_agent> | <msg_type> | <json_payload>")
                continue
            try:
                payload = json.loads(parts[2]) if parts[2] else {}
            except Exception as exc:
                console.print(f"Invalid JSON payload: {exc}")
                continue
            console.print(agent._a2a_send(parts[0], parts[1], payload))
            continue
        if user_text.startswith("/a2a delegate "):
            raw = user_text[len("/a2a delegate ") :].strip()
            parts = [p.strip() for p in raw.split("|")]
            if len(parts) != 3:
                console.print("Usage: /a2a delegate <to_agent> | <tool_name> | <json_args>")
                continue
            try:
                args = json.loads(parts[2]) if parts[2] else {}
            except Exception as exc:
                console.print(f"Invalid JSON args: {exc}")
                continue
            fn = getattr(agent, "_a2a_delegate_tool", None)
            if not callable(fn):
                console.print("A2A delegation unavailable.")
            else:
                console.print(fn(parts[0], parts[1], args, None))
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
