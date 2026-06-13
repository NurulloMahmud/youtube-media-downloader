"""Telegram bot — users paste a YouTube/Instagram URL to download, or a
token (from Instagram DM) to link their Instagram account."""

import asyncio
import logging
import re
import sys
from pathlib import Path

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.config import BASE_URL, TELEGRAM_BOT_TOKEN
from backend.database import SessionLocal
from backend.models import get_user_by_token, link_telegram
from backend.services.downloader import cleanup_job, get_job, start_download

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

SUPPORTED_DOMAINS = ['youtube.com', 'youtu.be', 'instagram.com']
MAX_UPLOAD_BYTES  = 50 * 1024 * 1024

# A token is exactly 12 lowercase hex characters
_TOKEN_RE = re.compile(r'^[0-9a-f]{12}$')

STATUS_TEXT = {
    'pending':           '⏳ Queued…',
    'fetching_info':     '🔍 Fetching video info…',
    'downloading_video': '📥 Downloading video…',
    'downloading_audio': '🎵 Extracting audio…',
    'completed':         '✅ Done!',
    'error':             '❌ Error',
}


def _is_url(text: str) -> bool:
    return any(d in text for d in SUPPORTED_DOMAINS)


def _is_token(text: str) -> bool:
    return bool(_TOKEN_RE.match(text.strip().lower()))


# ── Command handlers ──────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👋 *Welcome to VideoGrab Bot!*\n\n"
        "You can use me in two ways:\n\n"
        "1️⃣ *Download directly* — paste a YouTube or Instagram Reel URL and "
        "I'll send you the video + audio.\n\n"
        "2️⃣ *Link your Instagram* — DM 'start' to our Instagram account "
        "to get a token, then paste that token here to connect your accounts. "
        "After that, just forward any Reel to Instagram and it arrives here automatically.\n\n"
        "*Supported platforms:*\n"
        "▶️ YouTube — youtube.com / youtu.be\n"
        "📸 Instagram Reels — instagram.com/reel/",
        parse_mode="Markdown",
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "*How to use:*\n\n"
        "*Direct download:*\n"
        "1. Copy a YouTube or Instagram Reel URL\n"
        "2. Paste it here\n"
        "3. Receive video + audio\n\n"
        "*Instagram forwarding setup:*\n"
        "1. Follow our Instagram account\n"
        "2. DM 'start' to get your token\n"
        "3. Paste the token here to link\n"
        "4. Forward any Reel to Instagram — it arrives here automatically\n\n"
        "*Notes:*\n"
        "• Files over 50 MB are sent as download links\n"
        "• Files are available for 1 hour\n",
        parse_mode="Markdown",
    )


# ── Main message handler ──────────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text.strip()

    if _is_token(text):
        await _handle_token(update, text.lower())
    elif _is_url(text):
        await _handle_download(update, text)
    else:
        await update.message.reply_text(
            "I didn't recognise that.\n\n"
            "Send a YouTube or Instagram Reel URL to download it, "
            "or paste the token from your Instagram DM to link your account.\n\n"
            "Use /help for more info."
        )


# ── Token linking ─────────────────────────────────────────────────────

async def _handle_token(update: Update, token: str) -> None:
    chat_id = update.effective_chat.id
    db = SessionLocal()
    try:
        user = get_user_by_token(db, token)
        if not user:
            await update.message.reply_text(
                "❌ That token wasn't found. Check you copied it correctly from the Instagram DM.\n\n"
                "If you haven't started yet, DM 'start' to our Instagram account first."
            )
            return

        if user.telegram_chat_id and user.telegram_chat_id == chat_id:
            await update.message.reply_text(
                "✅ Your account is already linked! Just forward any Reel to our Instagram "
                "and the video + audio will arrive here."
            )
            return

        link_telegram(db, token, chat_id)
        await update.message.reply_text(
            "✅ *Linked!* Your Instagram and Telegram are now connected.\n\n"
            "Forward any Instagram Reel to our Instagram account and the "
            "video + audio will be sent here automatically.",
            parse_mode="Markdown",
        )
    except Exception:
        logger.exception("Error handling token %s for chat %s", token, chat_id)
        await update.message.reply_text("Something went wrong. Please try again.")
    finally:
        db.close()


# ── URL download ──────────────────────────────────────────────────────

async def _handle_download(update: Update, url: str) -> None:
    status_msg = await update.message.reply_text("⏳ Starting…")
    job_id = start_download(url)
    last_text = ""

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

    chat_id    = update.effective_chat.id
    video_path = job.get("video_path")
    audio_path = job.get("audio_path")
    video_url  = job.get("video_url")
    audio_url  = job.get("audio_url")
    title      = job.get("title", "video")

    await _safe_edit(status_msg, "📤 Sending files…")

    video_uploaded = await _send_file(
        update.get_bot() or update.message.get_bot(),
        chat_id,
        file_path=video_path,
        fallback_url=f"{BASE_URL}{video_url}" if video_url else None,
        send_fn="send_video",
        caption=f"🎬 {title}",
        extra_kwargs={"supports_streaming": True},
    )
    audio_uploaded = await _send_file(
        update.get_bot() or update.message.get_bot(),
        chat_id,
        file_path=audio_path,
        fallback_url=f"{BASE_URL}{audio_url}" if audio_url else None,
        send_fn="send_audio",
        caption=f"🎵 {title}",
        extra_kwargs={"title": title},
    )

    await _safe_edit(status_msg, "✅ Done! Files sent above.")
    cleanup_job(job_id, delete_files=(video_uploaded and audio_uploaded))


# ── Shared helpers ────────────────────────────────────────────────────

async def _send_file(bot, chat_id, file_path, fallback_url, send_fn, caption, extra_kwargs) -> bool:
    """Returns True if uploaded directly, False if fallback link was sent."""
    if not file_path:
        return True

    path = Path(file_path)
    if not path.exists():
        return True

    size = path.stat().st_size

    if size <= MAX_UPLOAD_BYTES:
        try:
            with open(path, "rb") as fh:
                await getattr(bot, send_fn)(
                    chat_id, **{send_fn.replace("send_", ""): fh},
                    caption=caption, **extra_kwargs,
                    write_timeout=300,
                    read_timeout=60,
                )
            return True
        except Exception as exc:
            logger.warning("Direct upload failed (%s): %s", send_fn, exc)

    size_mb = size / (1024 * 1024)
    kind    = "Video" if send_fn == "send_video" else "Audio"
    if fallback_url:
        await bot.send_message(
            chat_id,
            f"📥 {kind} ({size_mb:.1f} MB — too large for direct upload)\n"
            f"Download here: {fallback_url}",
        )
    else:
        await bot.send_message(chat_id, f"⚠️ {kind} ({size_mb:.1f} MB) could not be uploaded.")
    return False


async def _safe_edit(msg, text: str, **kwargs) -> None:
    try:
        await msg.edit_text(text, **kwargs)
    except TelegramError:
        pass


def _escape_md(text: str) -> str:
    return text.replace("*", "\\*").replace("`", "\\`").replace("_", "\\_")


# ── Entry point ───────────────────────────────────────────────────────

def main() -> None:
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN is not set.")
        sys.exit(1)

    app = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .read_timeout(60)
        .write_timeout(300)
        .connect_timeout(30)
        .pool_timeout(60)
        .build()
    )
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help",  cmd_help))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("VideoGrab Bot started — polling…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
