"""Telegram interface with chat-id whitelist and edit-based streaming."""

from __future__ import annotations

import time
from typing import Any

from config.settings import settings
from control.adb.qr_pairing import QRPairing
from utils.exporter import export_markdown
from vision.capture import capture_screen_png
from vision.gemini_vision import analyze_image


def is_whitelisted(user_id: str, allowed_chat_id: str | None = None) -> bool:
    whitelist = allowed_chat_id or settings.TELEGRAM_CHAT_ID
    return str(user_id) == str(whitelist)


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
        await update.message.reply_text(agent.status_text())

    async def on_health(update, _context: ContextTypes.DEFAULT_TYPE):
        if not await _authorized(update):
            return
        await update.message.reply_text(f"Health:\n{agent.status_text()}")

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
        timestamp = int(time.time())
        path = f"exports/{agent.session.current.name}_{timestamp}.md"
        export_markdown(agent.session.current.history, path)
        with open(path, "rb") as file_handle:
            await update.message.reply_document(document=InputFile(file_handle, filename=path.split("/")[-1]))

    async def on_screenshot(update, _context: ContextTypes.DEFAULT_TYPE):
        if not await _authorized(update):
            return
        try:
            png = capture_screen_png()
            await update.message.reply_photo(photo=png)
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
    app.add_handler(CommandHandler("screenshot", on_screenshot))
    app.add_handler(CommandHandler("qr", on_qr))
    app.add_handler(MessageHandler(filters.PHOTO, on_image))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    app.run_polling()
