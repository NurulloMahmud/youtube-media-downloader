"""Telegram bot — users paste a YouTube or Instagram URL and receive
the downloaded video and extracted audio as files (or download links
when files exceed Telegram's 50 MB upload limit)."""

import asyncio
import logging
import os
import sys
from pathlib import Path

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

# Allow running directly *or* as part of the package
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.config import BASE_URL, TELEGRAM_BOT_TOKEN
from backend.services.downloader import cleanup_job, get_job, start_download

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

SUPPORTED_DOMAINS = ['youtube.com', 'youtu.be', 'instagram.com']
MAX_UPLOAD_BYTES  = 50 * 1024 * 1024  # Telegram bot upload limit

STATUS_TEXT = {
    'pending':           '⏳ Queued…',
    'fetching_info':     '🔍 Fetching video info…',
    'downloading_video': '📥 Downloading video…',
    'downloading_audio': '🎵 Extracting audio…',
    'completed':         '✅ Done!',
    'error':             '❌ Error',
}


def _is_supported(text: str) -> bool:
    return any(d in text for d in SUPPORTED_DOMAINS)


# ── Command handlers ─────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👋 *Welcome to VideoGrab Bot!*\n\n"
        "Send me a YouTube or Instagram Reels link and I'll download the "
        "video and extract the audio for you.\n\n"
        "*Supported:*\n"
        "▶️ YouTube — youtube.com / youtu.be\n"
        "📸 Instagram Reels — instagram.com/reels/\n\n"
        "Just paste a URL to get started!",
        parse_mode="Markdown",
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "*How to use:*\n"
        "1. Copy a YouTube or Instagram Reel URL\n"
        "2. Paste it here and send\n"
        "3. Wait while I download and process it\n"
        "4. Receive your video and audio files\n\n"
        "*Notes:*\n"
        "• Files over 50 MB are sent as download links instead\n"
        "• Files are deleted from the server after 1 hour\n"
        "• Use /start to see the welcome message",
        parse_mode="Markdown",
    )


# ── URL handler ──────────────────────────────────────────────────────

async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    url = update.message.text.strip()

    if not _is_supported(url):
        await update.message.reply_text(
            "❌ *Unsupported URL*\n\n"
            "Please send a valid YouTube or Instagram link.\n\n"
            "Examples:\n"
            "• https://youtube.com/watch?v=...\n"
            "• https://youtu.be/...\n"
            "• https://instagram.com/reels/...",
            parse_mode="Markdown",
        )
        return

    status_msg = await update.message.reply_text("⏳ Starting…")
    job_id = start_download(url)
    last_text = ""

    # ── Poll until done ──────────────────────────────────────────────
    while True:
        await asyncio.sleep(2)
        job = get_job(job_id)

        if not job:
            await _safe_edit(status_msg, "❌ Job lost. Please try again.")
            return

        status   = job["status"]
        progress = job.get("progress", "0%")
        title    = job.get("title", "")

        lines = [STATUS_TEXT.get(status, status)]
        if title:
            lines.append(f"📺 *{_escape_md(title)}*")
        if status in ("downloading_video", "downloading_audio"):
            lines.append(f"`{progress}`")

        new_text = "\n".join(lines)
        if new_text != last_text:
            await _safe_edit(status_msg, new_text, parse_mode="Markdown")
            last_text = new_text

        if status == "completed":
            break
        if status == "error":
            error = job.get("error", "Unknown error")
            await _safe_edit(
                status_msg,
                f"❌ *Download failed*\n\n`{_escape_md(error)}`",
                parse_mode="Markdown",
            )
            cleanup_job(job_id)
            return

    # ── Send files ───────────────────────────────────────────────────
    chat_id     = update.effective_chat.id
    video_path  = job.get("video_path")
    audio_path  = job.get("audio_path")
    video_url   = job.get("video_url")
    audio_url   = job.get("audio_url")
    title       = job.get("title", "video")

    await _safe_edit(status_msg, "📤 Sending files…")

    await _send_file(
        context,
        chat_id,
        file_path=video_path,
        fallback_url=f"{BASE_URL}{video_url}" if video_url else None,
        send_fn="send_video",
        caption=f"🎬 {title}",
        extra_kwargs={"supports_streaming": True},
    )

    await _send_file(
        context,
        chat_id,
        file_path=audio_path,
        fallback_url=f"{BASE_URL}{audio_url}" if audio_url else None,
        send_fn="send_audio",
        caption=f"🎵 {title}",
        extra_kwargs={"title": title},
    )

    await _safe_edit(status_msg, "✅ Done! Files sent above.")
    cleanup_job(job_id)


# ── Helpers ──────────────────────────────────────────────────────────

async def _send_file(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    file_path: str | None,
    fallback_url: str | None,
    send_fn: str,
    caption: str,
    extra_kwargs: dict,
) -> None:
    if not file_path:
        return

    path = Path(file_path)
    if not path.exists():
        return

    size = path.stat().st_size

    if size <= MAX_UPLOAD_BYTES:
        try:
            with open(path, "rb") as fh:
                await getattr(context.bot, send_fn)(
                    chat_id, **{send_fn.replace("send_", ""): fh},
                    caption=caption, **extra_kwargs,
                    write_timeout=300,
                    read_timeout=60,
                )
            return
        except Exception as exc:
            logger.warning("Direct upload failed (%s), falling back to link: %s", send_fn, exc)

    # Fallback: send a download link
    size_mb = size / (1024 * 1024)
    kind    = "Video" if send_fn == "send_video" else "Audio"
    if fallback_url:
        await context.bot.send_message(
            chat_id,
            f"📥 *{kind}* ({size_mb:.1f} MB — too large for direct upload)\n"
            f"Download here: {fallback_url}",
            parse_mode="Markdown",
        )
    else:
        await context.bot.send_message(
            chat_id,
            f"⚠️ {kind} file is {size_mb:.1f} MB and could not be uploaded.",
        )


async def _safe_edit(msg, text: str, **kwargs) -> None:
    try:
        await msg.edit_text(text, **kwargs)
    except TelegramError:
        pass


def _escape_md(text: str) -> str:
    """Minimal Markdown V1 escaping for inline code/bold usage."""
    return text.replace("*", "\\*").replace("`", "\\`").replace("_", "\\_")


# ── Entry point ──────────────────────────────────────────────────────

def main() -> None:
    token = TELEGRAM_BOT_TOKEN
    if not token:
        logger.error(
            "TELEGRAM_BOT_TOKEN is not set. "
            "Create a .env file or set the environment variable."
        )
        sys.exit(1)

    app = (
        Application.builder()
        .token(token)
        .read_timeout(60)
        .write_timeout(300)   # 5 min for large file uploads
        .connect_timeout(30)
        .pool_timeout(60)
        .build()
    )
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help",  cmd_help))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url))

    logger.info("VideoGrab Bot started — polling…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
