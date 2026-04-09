"""Telegram interface with chat-id whitelist and edit-based streaming.

Fixes applied:
- 1.2: integer-safe whitelist check; raise RuntimeError at startup if TELEGRAM_CHAT_ID is empty.
- 1.2: log every rejected authorization attempt.
"""

from __future__ import annotations

from io import BytesIO
from collections import OrderedDict, deque
import asyncio
import contextlib
import inspect
import json
import queue
import threading
import time
from typing import Any

from config.settings import settings
from control.adb.qr_pairing import QRPairing
from vision.capture import capture_screen_png
from vision.gemini_vision import analyze_image
from interfaces.cli import format_usage_message
from interfaces.key_manager import summarize_env_keys
from interfaces.model_manager import (
    benchmark_providers,
    delete_ollama_model,
    list_ollama_models,
    provider_key_snapshot,
    pull_ollama_model,
    recommend_provider,
)
from utils.events import format_event_log
from utils.goals import format_goal_list
from utils.health import format_health_table, summarize_health
from utils.logger import get_logger

_log = get_logger(__name__)
_TELEGRAM_RATE_WINDOW_SECONDS = 60
_TELEGRAM_RATE_LIMIT = 12
_TELEGRAM_HEAVY_RATE_LIMIT = 2
_RATE_LIMIT_MSG = "Too many commands too quickly. Please slow down for a minute."


def _run_sync_or_async(value: Any) -> Any:
    if inspect.isawaitable(value):
        return asyncio.run(value)
    return value


def is_whitelisted(user_id: str | int, allowed_chat_id: str | None = None) -> bool:
    """Type-safe integer comparison for Telegram chat ID whitelist (fix 1.2)."""
    whitelist = allowed_chat_id or settings.TELEGRAM_CHAT_ID
    if not whitelist or not str(whitelist).strip():
        return False
    try:
        return int(user_id) == int(whitelist)
    except (ValueError, TypeError):
        return False


def format_status_message(status_text: str) -> str:
    try:
        payload = json.loads(status_text)
    except Exception:
        return status_text

    health_summary = payload.get("health_summary") or {}
    lines = [
        "NOVA Status",
        f"Session            | {payload.get('session', 'unknown')}",
        f"Session ID         | {payload.get('session_id', '')}",
        f"Provider           | {payload.get('provider_last', 'unknown')}",
        f"Memory Mode        | {payload.get('memory_mode', 'unknown')}",
        f"Emotion            | {payload.get('emotion', 'neutral')}",
        f"Cloud Keys Active  | {payload.get('active_cloud_keys', 0)}",
        f"Muted              | {payload.get('muted', False)}",
        f"Tailscale          | {payload.get('tailscale_ip', '') or 'n/a'}",
        f"Health             | ok={health_summary.get('ok', 0)} down={health_summary.get('down', 0)} restarting={health_summary.get('restarting', 0)} failed={health_summary.get('restart_failed', 0)}",
        "",
        "Usage Today",
        str(payload.get("usage_today", "")),
        "",
        "Usage Week",
        str(payload.get("usage_week", "")),
    ]
    return "\n".join(lines).strip()


def telegram_photo_from_png(png: bytes, filename: str = "screenshot.png"):
    buffer = BytesIO(png)
    buffer.name = filename
    buffer.seek(0)
    return buffer


async def _stream_text(message: Any, context: Any, agent: Any, prompt_text: str) -> None:
    if not message:
        return

    placeholder = await message.reply_text("⏳")
    buffer = ""
    last_edit = 0.0

    token_queue: queue.Queue[str | None] = queue.Queue()
    worker_error: list[str] = []

    def _worker() -> None:
        try:
            for token in agent.ask_stream(prompt_text):
                token_queue.put(token)
        except Exception as exc:
            worker_error.append(str(exc))
        finally:
            token_queue.put(None)

    threading.Thread(target=_worker, daemon=True).start()

    while True:
        token = await asyncio.to_thread(token_queue.get)
        if token is None:
            break
        buffer += token
        now = time.time()
        if now - last_edit > 1.5:
            try:
                await context.bot.edit_message_text(
                    text=buffer + " ▌",
                    chat_id=placeholder.chat_id,
                    message_id=placeholder.message_id,
                )
            except Exception:
                pass
            last_edit = now

    if not buffer:
        if worker_error:
            buffer = f"(error: {worker_error[-1]})"
        else:
            buffer = "(no output)"
    await context.bot.edit_message_text(
        text=buffer,
        chat_id=placeholder.chat_id,
        message_id=placeholder.message_id,
    )


async def _stream_reply(update: Any, context: Any, agent: Any) -> None:
    message = update.message
    if not message:
        return
    await _stream_text(message, context, agent, message.text or "")


def run_telegram_bot(
    agent: Any,
    token: str | None = None,
    allowed_chat_id: str | None = None,
    stop_event: Any | None = None,
) -> None:
    bot_token = token or settings.TELEGRAM_BOT_TOKEN
    if not bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is missing")

    # fix 1.2: fail fast if whitelist is empty
    effective_chat_id = allowed_chat_id or settings.TELEGRAM_CHAT_ID
    if not effective_chat_id or not str(effective_chat_id).strip():
        raise RuntimeError(
            "TELEGRAM_CHAT_ID must be set when the Telegram bot is enabled. "
            "Without it the bot is open to any Telegram user."
        )

    try:
        from telegram import InputFile
        from telegram.ext import (
            ApplicationBuilder,
            CommandHandler,
            ContextTypes,
            MessageHandler,
            filters,
        )
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("python-telegram-bot is not installed") from exc

    command_windows: OrderedDict[int, deque[float]] = OrderedDict()
    heavy_command_windows: OrderedDict[int, deque[float]] = OrderedDict()

    def _allow_command(user_id: int) -> bool:
        if len(command_windows) > 1000:
            command_windows.popitem(last=False)
        now = time.monotonic()
        window = command_windows.get(user_id)
        if window is None:
            window = deque()
            command_windows[user_id] = window
        else:
            command_windows.move_to_end(user_id)
        while window and (now - window[0]) > _TELEGRAM_RATE_WINDOW_SECONDS:
            window.popleft()
        if len(window) >= _TELEGRAM_RATE_LIMIT:
            return False
        window.append(now)
        return True

    def _allow_heavy_command(user_id: int) -> bool:
        if len(heavy_command_windows) > 1000:
            heavy_command_windows.popitem(last=False)
        now = time.monotonic()
        window = heavy_command_windows.get(user_id)
        if window is None:
            window = deque()
            heavy_command_windows[user_id] = window
        else:
            heavy_command_windows.move_to_end(user_id)
        while window and (now - window[0]) > _TELEGRAM_RATE_WINDOW_SECONDS:
            window.popleft()
        if len(window) >= _TELEGRAM_HEAVY_RATE_LIMIT:
            return False
        window.append(now)
        return True

    async def _authorized(update) -> bool:
        user = update.effective_user
        if not user:
            return False
        authorized = is_whitelisted(user.id, allowed_chat_id=effective_chat_id)
        if not authorized:
            # fix 1.2: log every rejected attempt
            _log.warning(
                f"Telegram auth rejected: user_id={user.id} username={user.username!r} "
                f"whitelist={effective_chat_id!r}"
            )
            return False
        if not _allow_command(int(user.id)):
            if update.message:
                await update.message.reply_text(_RATE_LIMIT_MSG)
            return False
        return authorized

    async def on_status(update, _context: ContextTypes.DEFAULT_TYPE):
        if not await _authorized(update):
            return
        await update.message.reply_text(format_status_message(agent.status_text()))

    async def on_health(update, _context: ContextTypes.DEFAULT_TYPE):
        if not await _authorized(update):
            return
        health_items = agent.health.status_table()
        header = summarize_health(health_items)
        body = format_health_table(health_items)
        await update.message.reply_text(f"Health summary: {header}\n\n{body}")

    async def on_session(update, context: ContextTypes.DEFAULT_TYPE):
        if not await _authorized(update):
            return
        if not context.args:
            await update.message.reply_text("Usage: /session <name>")
            return
        name = " ".join(context.args).strip()
        state = agent.switch_session(name)
        await update.message.reply_text(f"Switched to {state.name} ({state.session_id})")

    async def on_export(update, _context: ContextTypes.DEFAULT_TYPE):
        if not await _authorized(update):
            return
        user = update.effective_user
        if user and not _allow_heavy_command(int(user.id)):
            await update.message.reply_text("This command is rate-limited to 2 requests per minute.")
            return
        path = agent.export_session("md")
        try:
            with open(path, "rb") as file_handle:
                await update.message.reply_document(document=InputFile(file_handle, filename=path.split("/")[-1]))
        except Exception as exc:
            await update.message.reply_text(f"Export failed: {exc}")

    async def on_goals(update, _context: ContextTypes.DEFAULT_TYPE):
        if not await _authorized(update):
            return
        await update.message.reply_text(format_goal_list(agent.list_goals()))

    async def on_alerts(update, _context: ContextTypes.DEFAULT_TYPE):
        if not await _authorized(update):
            return
        await update.message.reply_text(format_event_log(agent.recent_events()))

    async def on_goal(update, context: ContextTypes.DEFAULT_TYPE):
        if not await _authorized(update):
            return
        user = update.effective_user
        if user and not _allow_heavy_command(int(user.id)):
            await update.message.reply_text("This command is rate-limited to 2 requests per minute.")
            return
        text = " ".join(context.args).strip()
        if not text:
            await update.message.reply_text("Usage: /goal <goal description>")
            return
        if len(text) > 500:
            text = text[:500].rstrip() + "..."
        result = agent.add_goal(text)
        if result.get("status") not in {"planning", "pending"}:
            await update.message.reply_text(f"Goal planning failed: {result}")
            return
        await update.message.reply_text(
            f"Queued goal {result['id']}.\n"
            f"Status: {result['status']}\n"
            f"Goal: {result['goal']}"
        )

    async def on_resume_goal(update, context: ContextTypes.DEFAULT_TYPE):
        if not await _authorized(update):
            return
        user = update.effective_user
        if user and not _allow_heavy_command(int(user.id)):
            await update.message.reply_text("This command is rate-limited to 2 requests per minute.")
            return
        if not context.args:
            await update.message.reply_text("Usage: /resume_goal <goal_id>")
            return
        goal_id = context.args[0].strip()
        result = agent.resume_goal(goal_id)
        await update.message.reply_text(f"{result}")

    async def on_cancel_goal(update, context: ContextTypes.DEFAULT_TYPE):
        if not await _authorized(update):
            return
        if not context.args:
            await update.message.reply_text("Usage: /cancel_goal <goal_id>")
            return
        goal_id = context.args[0].strip()
        result = agent.cancel_goal(goal_id)
        await update.message.reply_text(f"{result}")

    async def on_mute(update, _context: ContextTypes.DEFAULT_TYPE):
        if not await _authorized(update):
            return
        agent.set_muted(True)
        await update.message.reply_text("Muted proactive alerts and autonomy notifications.")

    async def on_unmute(update, _context: ContextTypes.DEFAULT_TYPE):
        if not await _authorized(update):
            return
        agent.set_muted(False)
        await update.message.reply_text("Unmuted proactive alerts and autonomy notifications.")

    async def on_usage(update, _context: ContextTypes.DEFAULT_TYPE):
        if not await _authorized(update):
            return
        session_id = agent.session.current.session_id
        summary = agent.usage.today_summary(session_id=session_id)
        await update.message.reply_text(format_usage_message("Usage today", summary))

    async def on_usage_week(update, _context: ContextTypes.DEFAULT_TYPE):
        if not await _authorized(update):
            return
        session_id = agent.session.current.session_id
        summary = agent.usage.weekly_summary(session_id=session_id)
        await update.message.reply_text(format_usage_message("Usage this week", summary))

    async def on_screenshot(update, _context: ContextTypes.DEFAULT_TYPE):
        if not await _authorized(update):
            return
        user = update.effective_user
        if user and not _allow_heavy_command(int(user.id)):
            await update.message.reply_text("This command is rate-limited to 2 requests per minute.")
            return
        try:
            png = capture_screen_png()
            await update.message.reply_photo(photo=InputFile(telegram_photo_from_png(png), filename="screenshot.png"))
        except Exception as exc:
            await update.message.reply_text(f"Screenshot failed: {exc}")

    async def on_qr(update, context: ContextTypes.DEFAULT_TYPE):
        if not await _authorized(update):
            return
        user = update.effective_user
        if user and not _allow_heavy_command(int(user.id)):
            await update.message.reply_text("This command is rate-limited to 2 requests per minute.")
            return
        prefer_remote = bool(context.args and context.args[0].strip().lower() == "remote")
        try:
            pairing = QRPairing(adb_port=settings.ADB_PORT)
            out_path = pairing.generate(prefer_remote=prefer_remote)
            with open(out_path, "rb") as fh:
                await update.message.reply_photo(photo=fh)
            await update.message.reply_text(f"ADB QR ready ({'remote' if prefer_remote else 'local'} mode).")
        except Exception as exc:
            await update.message.reply_text(f"QR generation failed: {exc}")

    async def on_keys(update, _context: ContextTypes.DEFAULT_TYPE):
        if not await _authorized(update):
            return
        summary = summarize_env_keys(settings)
        if not summary:
            await update.message.reply_text("No configured keys found in current environment.")
            return
        lines = ["Configured key pools (masked):"]
        for provider in sorted(summary.keys()):
            masked = summary.get(provider, [])
            lines.append(f"- {provider}: {', '.join(masked)}")
        lines.append("")
        lines.append("Use GUI Key Manager for encrypted edits/storage.")
        await update.message.reply_text("\n".join(lines))

    async def on_models(update, context: ContextTypes.DEFAULT_TYPE):
        if not await _authorized(update):
            return
        args = [a.strip() for a in (context.args or []) if a.strip()]
        sub = args[0].lower() if args else "list"
        try:
            if sub in {"list", "ls"}:
                models = list_ollama_models()
                if not models:
                    await update.message.reply_text("No Ollama models found.")
                    return
                lines = ["Installed Ollama models:"]
                for item in models[:40]:
                    name = item.get("name") or item.get("model") or "unknown"
                    size = item.get("size") or ""
                    lines.append(f"- {name} ({size})")
                await update.message.reply_text("\n".join(lines))
                return

            if sub == "pull":
                model = " ".join(args[1:]).strip() if len(args) > 1 else ""
                if not model:
                    await update.message.reply_text("Usage: /models pull <model_name>")
                    return
                await update.message.reply_text(f"Pulling {model} ... this may take a while.")
                result = pull_ollama_model(model)
                await update.message.reply_text(str(result))
                return

            if sub in {"delete", "rm"}:
                model = " ".join(args[1:]).strip() if len(args) > 1 else ""
                if not model:
                    await update.message.reply_text("Usage: /models delete <model_name>")
                    return
                result = delete_ollama_model(model)
                await update.message.reply_text(str(result))
                return

            if sub in {"benchmark", "bench"}:
                rows = benchmark_providers(agent)
                await update.message.reply_text(json.dumps(rows, ensure_ascii=False, indent=2)[:3900])
                return

            if sub in {"recommend", "auto"}:
                rec = recommend_provider(agent)
                await update.message.reply_text(json.dumps(rec, ensure_ascii=False, indent=2)[:3900])
                return

            if sub in {"keys", "health"}:
                snap = provider_key_snapshot(agent)
                await update.message.reply_text(json.dumps(snap, ensure_ascii=False, indent=2)[:3900])
                return

            await update.message.reply_text(
                "Usage: /models list|pull <name>|delete <name>|benchmark|recommend|keys"
            )
        except Exception as exc:
            await update.message.reply_text(f"Model command failed: {exc}")

    async def on_privacy(update, context: ContextTypes.DEFAULT_TYPE):
        if not await _authorized(update):
            return
        if not context.args:
            mode = getattr(agent, "_get_session_privacy_mode", lambda *_: "full_cloud")()
            await update.message.reply_text(f"Current session privacy mode: {mode}")
            return
        raw = context.args[0].strip().lower()
        setter = getattr(agent, "_set_session_privacy_mode", None)
        if not callable(setter):
            await update.message.reply_text("Privacy controls unavailable.")
            return
        selected = setter(raw)
        await update.message.reply_text(f"Session privacy mode set to: {selected}")

    async def on_mission(update, context: ContextTypes.DEFAULT_TYPE):
        if not await _authorized(update):
            return
        args = [a.strip() for a in (context.args or []) if a.strip()]
        if not args or args[0].lower() == "list":
            await update.message.reply_text(str(agent._mission_list()))
            return
        sub = args[0].lower()
        if sub == "enable" and len(args) >= 2:
            await update.message.reply_text(str(agent._mission_enable(args[1])))
            return
        if sub == "disable" and len(args) >= 2:
            await update.message.reply_text(str(agent._mission_disable(args[1])))
            return
        if sub == "run" and len(args) >= 2:
            await update.message.reply_text(str(agent._mission_run_now(args[1])))
            return
        if sub == "add":
            # /mission add name | schedule | goal
            raw = (update.message.text or "").split(" ", 2)
            body = raw[2] if len(raw) >= 3 else ""
            parts = [p.strip() for p in body.split("|")]
            if len(parts) != 3:
                await update.message.reply_text("Usage: /mission add <name> | <schedule> | <goal>")
                return
            await update.message.reply_text(str(agent._mission_add(parts[0], parts[1], parts[2], True)))
            return
        await update.message.reply_text("Usage: /mission list|enable <name>|disable <name>|run <name>|add ...")

    async def on_theme(update, context: ContextTypes.DEFAULT_TYPE):
        if not await _authorized(update):
            return
        args = [a.strip() for a in (context.args or []) if a.strip()]
        getter = getattr(agent, "get_theme_lock", None)
        setter = getattr(agent, "set_theme_lock", None)
        if not args:
            current = str(getter()) if callable(getter) else "auto"
            await update.message.reply_text(f"Current theme mode: {current}")
            return
        if not callable(setter):
            await update.message.reply_text("Theme controls unavailable.")
            return
        selected = str(setter(args[0]))
        if selected == "auto":
            await update.message.reply_text("Theme auto-switch enabled.")
        else:
            await update.message.reply_text(f"Theme locked to '{selected}'.")

    async def on_a2a(update, context: ContextTypes.DEFAULT_TYPE):
        if not await _authorized(update):
            return
        args = [a.strip() for a in (context.args or []) if a.strip()]
        if not args or args[0].lower() == "peers":
            await update.message.reply_text(str(agent._a2a_peers()))
            return
        if args[0].lower() == "inbox":
            await update.message.reply_text(str(agent._a2a_inbox(20)))
            return
        if args[0].lower() == "send":
            text = update.message.text or ""
            body = text.split(" ", 2)[2] if len(text.split(" ", 2)) >= 3 else ""
            parts = [p.strip() for p in body.split("|")]
            if len(parts) != 3:
                await update.message.reply_text("Usage: /a2a send <to_agent> | <msg_type> | <json_payload>")
                return
            try:
                payload = json.loads(parts[2]) if parts[2] else {}
            except Exception as exc:
                await update.message.reply_text(f"Invalid JSON payload: {exc}")
                return
            await update.message.reply_text(str(agent._a2a_send(parts[0], parts[1], payload)))
            return
        if args[0].lower() == "delegate":
            text = update.message.text or ""
            body = text.split(" ", 2)[2] if len(text.split(" ", 2)) >= 3 else ""
            parts = [p.strip() for p in body.split("|")]
            if len(parts) != 3:
                await update.message.reply_text("Usage: /a2a delegate <to_agent> | <tool_name> | <json_args>")
                return
            try:
                payload = json.loads(parts[2]) if parts[2] else {}
            except Exception as exc:
                await update.message.reply_text(f"Invalid JSON args: {exc}")
                return
            fn = getattr(agent, "_a2a_delegate_tool", None)
            if not callable(fn):
                await update.message.reply_text("A2A delegation unavailable.")
                return
            await update.message.reply_text(str(fn(parts[0], parts[1], payload, None)))
            return
        await update.message.reply_text("Usage: /a2a peers|inbox|send ...|delegate ...")

    async def on_image(update, context: ContextTypes.DEFAULT_TYPE):
        if not await _authorized(update):
            return
        if not update.message.photo:
            return
        photo = update.message.photo[-1]
        telegram_file = await photo.get_file()
        image_bytes = await telegram_file.download_as_bytearray()
        analysis = analyze_image(bytes(image_bytes))
        prompt = (
            "User shared an image. Analyze this context and assist.\n"
            f"Image analysis JSON: {analysis}"
        )
        await _stream_text(update.message, context, agent, prompt)

    async def on_message(update, context: ContextTypes.DEFAULT_TYPE):
        if not await _authorized(update):
            return
        text = (update.message.text or "").strip() if update.message else ""
        if len(text) > 50_000:
            await update.message.reply_text("Input too long. Please keep messages under 50,000 characters.")
            return
        await _stream_reply(update, context, agent)

    app = ApplicationBuilder().token(bot_token).build()
    app.add_handler(CommandHandler("status", on_status))
    app.add_handler(CommandHandler("health", on_health))
    app.add_handler(CommandHandler("session", on_session))
    app.add_handler(CommandHandler("export", on_export))
    app.add_handler(CommandHandler("goals", on_goals))
    app.add_handler(CommandHandler("alerts", on_alerts))
    app.add_handler(CommandHandler("goal", on_goal))
    app.add_handler(CommandHandler("resume_goal", on_resume_goal))
    app.add_handler(CommandHandler("cancel_goal", on_cancel_goal))
    app.add_handler(CommandHandler("mute", on_mute))
    app.add_handler(CommandHandler("unmute", on_unmute))
    app.add_handler(CommandHandler("usage", on_usage))
    app.add_handler(CommandHandler("usage_week", on_usage_week))
    app.add_handler(CommandHandler("screenshot", on_screenshot))
    app.add_handler(CommandHandler("qr", on_qr))
    app.add_handler(CommandHandler("keys", on_keys))
    app.add_handler(CommandHandler("models", on_models))
    app.add_handler(CommandHandler("privacy", on_privacy))
    app.add_handler(CommandHandler("mission", on_mission))
    app.add_handler(CommandHandler("theme", on_theme))
    app.add_handler(CommandHandler("a2a", on_a2a))
    app.add_handler(MessageHandler(filters.PHOTO, on_image))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    if stop_event is None:
        app.run_polling()
        return

    # Graceful shutdown path for embedding in a managed app lifecycle.
    try:
        _run_sync_or_async(app.initialize())
        _run_sync_or_async(app.start())
    except Exception as exc:
        _log.exception("Telegram app startup failed: %s", exc)
        return
    updater = getattr(app, "updater", None)
    polling_thread: threading.Thread | None = None
    if updater is not None:
        updater.start_polling()
    else:
        # Newer python-telegram-bot versions may not expose updater.
        # Run polling in a background thread so stop_event can still be honored.
        def _poll() -> None:
            try:
                app.run_polling(stop_signals=None)
            except Exception as exc:
                _log.exception("Telegram polling thread crashed: %s", exc)
        polling_thread = threading.Thread(target=_poll, daemon=True)
        polling_thread.start()
    try:
        while not stop_event.is_set():
            time.sleep(0.2)
    finally:
        if updater is not None:
            with contextlib.suppress(Exception):
                updater.stop()
        else:
            stop_running = getattr(app, "stop_running", None)
            if callable(stop_running):
                with contextlib.suppress(Exception):
                    stop_running()
            if polling_thread is not None and polling_thread.is_alive():
                polling_thread.join(timeout=2.0)
        with contextlib.suppress(Exception):
            _run_sync_or_async(app.stop())
        with contextlib.suppress(Exception):
            _run_sync_or_async(app.shutdown())
