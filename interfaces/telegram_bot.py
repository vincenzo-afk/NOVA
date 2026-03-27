"""Telegram interface with chat-id whitelist and edit-based streaming."""

from __future__ import annotations

from io import BytesIO
import json
import time
from typing import Any

from config.settings import settings
from control.adb.qr_pairing import QRPairing
from vision.capture import capture_screen_png
from vision.gemini_vision import analyze_image
from interfaces.cli import format_usage_message
from utils.events import format_event_log
from utils.goals import format_goal_list
from utils.health import format_health_table, summarize_health


def is_whitelisted(user_id: str, allowed_chat_id: str | None = None) -> bool:
    whitelist = allowed_chat_id or settings.TELEGRAM_CHAT_ID
    return str(user_id) == str(whitelist)


def format_status_message(status_text: str) -> str:
    try:
        payload = json.loads(status_text)
    except Exception:
        return status_text

    health_summary = payload.get("health_summary") or {}
    lines = [
        "JARVIS Status",
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

    for token in agent.ask_stream(prompt_text):
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


def run_telegram_bot(agent: Any, token: str | None = None, allowed_chat_id: str | None = None) -> None:
    bot_token = token or settings.TELEGRAM_BOT_TOKEN
    if not bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is missing")

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

    async def _authorized(update) -> bool:
        user = update.effective_user
        return bool(user and is_whitelisted(str(user.id), allowed_chat_id=allowed_chat_id))

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
        path = agent.export_session("md")
        with open(path, "rb") as file_handle:
            await update.message.reply_document(document=InputFile(file_handle, filename=path.split("/")[-1]))

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
        text = " ".join(context.args).strip()
        if not text:
            await update.message.reply_text("Usage: /goal <goal description>")
            return
        result = agent.add_goal(text)
        if result.get("status") != "pending":
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
        try:
            png = capture_screen_png()
            await update.message.reply_photo(photo=InputFile(telegram_photo_from_png(png), filename="screenshot.png"))
        except Exception as exc:
            await update.message.reply_text(f"Screenshot failed: {exc}")

    async def on_qr(update, context: ContextTypes.DEFAULT_TYPE):
        if not await _authorized(update):
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
    app.add_handler(MessageHandler(filters.PHOTO, on_image))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    app.run_polling()
