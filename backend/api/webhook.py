"""Instagram webhook — verifies the endpoint and handles incoming DMs."""

import logging
import re

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request, Response

from ..config import BASE_URL, IG_WEBHOOK_VERIFY_TOKEN, TELEGRAM_BOT_TOKEN
from ..database import SessionLocal
from ..models import create_user, get_user_by_ig_id, get_user_by_telegram_id
from ..services.instagram_api import get_user_info, is_follower, send_message

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhook", tags=["webhook"])

# Rough pattern for an Instagram Reel / post URL
_REEL_RE = re.compile(r"https?://(?:www\.)?instagram\.com/(?:reel|p)/[\w-]+", re.I)


# ── Webhook verification (GET) ────────────────────────────────────────

@router.get("/instagram")
async def verify_webhook(
    hub_mode: str = Query(alias="hub.mode", default=""),
    hub_verify_token: str = Query(alias="hub.verify_token", default=""),
    hub_challenge: str = Query(alias="hub.challenge", default=""),
):
    if hub_mode == "subscribe" and hub_verify_token == IG_WEBHOOK_VERIFY_TOKEN:
        logger.info("Webhook verified by Meta")
        return Response(content=hub_challenge, media_type="text/plain")
    raise HTTPException(status_code=403, detail="Verification failed")


# ── Webhook events (POST) ─────────────────────────────────────────────

@router.post("/instagram")
async def receive_webhook(request: Request, background_tasks: BackgroundTasks):
    # Always return 200 immediately — Meta will retry otherwise
    payload = await request.json()
    background_tasks.add_task(_handle_payload, payload)
    return {"status": "ok"}


# ── Background processing ─────────────────────────────────────────────

async def _handle_payload(payload: dict) -> None:
    if payload.get("object") != "instagram":
        return

    for entry in payload.get("entry", []):
        for event in entry.get("messaging", []):
            sender_id = event.get("sender", {}).get("id", "")
            message   = event.get("message", {})
            if not sender_id or not message or message.get("is_echo"):
                continue
            await _handle_message(sender_id, message)


async def _handle_message(igsid: str, message: dict) -> None:
    text = (message.get("text") or "").strip()
    attachments = message.get("attachments", [])

    # ── "start" command ───────────────────────────────────────────────
    if text.lower() == "start":
        await _handle_start(igsid)
        return

    # ── Forwarded reel or pasted reel URL ────────────────────────────
    reel_url = _extract_reel_url(text, attachments)
    if reel_url:
        await _handle_reel(igsid, reel_url)
        return

    # ── Anything else — ignore silently ──────────────────────────────
    logger.debug("Ignored message from %s: %r", igsid, text[:80])


async def _handle_start(igsid: str) -> None:
    db = SessionLocal()
    try:
        existing = get_user_by_ig_id(db, igsid)
        if existing:
            # Already registered — resend token, don't create a new one
            await send_message(
                igsid,
                f"You already have a token: {existing.token}\n\n"
                f"Open @KontentYuklovchiBot on Telegram, paste your token there "
                f"to link your account, then forward any Reel to this chat and "
                f"I'll deliver the video + audio straight to Telegram.",
            )
            return

        # Check follower status before registering
        info = await get_user_info(igsid)
        if not is_follower(info):
            await send_message(
                igsid,
                "Please follow our Instagram account first, then send 'start' again "
                "to get your access token.",
            )
            return

        ig_username = info.get("username") or info.get("name")
        user = create_user(db, igsid, ig_username)

        await send_message(
            igsid,
            f"Welcome! Your token is:\n\n{user.token}\n\n"
            f"Open @KontentYuklovchiBot on Telegram and paste this token to link "
            f"your account. After that, forward any Instagram Reel to this chat "
            f"and I'll send the video + audio directly to your Telegram.",
        )
    except Exception:
        logger.exception("Error in _handle_start for %s", igsid)
    finally:
        db.close()


async def _handle_reel(igsid: str, reel_url: str) -> None:
    from ..services.downloader import get_job, start_download

    db = SessionLocal()
    try:
        user = get_user_by_ig_id(db, igsid)
        if not user:
            await send_message(
                igsid,
                "Send 'start' first to register and link your Telegram account.",
            )
            return

        if not user.telegram_chat_id:
            await send_message(
                igsid,
                f"You haven't linked your Telegram yet.\n\n"
                f"Your token is: {user.token}\n\n"
                f"Open @KontentYuklovchiBot, paste the token, then try forwarding again.",
            )
            return

        telegram_chat_id = user.telegram_chat_id
    finally:
        db.close()

    # Kick off the download — delivery happens via the Telegram bot helper
    await send_message(igsid, "Got it! Downloading your Reel — check Telegram shortly.")
    job_id = start_download(reel_url)
    import asyncio
    asyncio.create_task(_deliver_to_telegram(job_id, telegram_chat_id))


async def _deliver_to_telegram(job_id: str, telegram_chat_id: int) -> None:
    import asyncio
    from telegram import Bot
    from ..services.downloader import get_job, cleanup_job

    bot = Bot(token=TELEGRAM_BOT_TOKEN)

    # Poll until done (max 5 min)
    for _ in range(150):
        await asyncio.sleep(2)
        job = get_job(job_id)
        if not job:
            break
        if job["status"] == "completed":
            break
        if job["status"] == "error":
            await bot.send_message(
                telegram_chat_id,
                f"❌ Download failed: {job.get('error', 'unknown error')}",
            )
            cleanup_job(job_id)
            return

    job = get_job(job_id)
    if not job or job["status"] != "completed":
        await bot.send_message(telegram_chat_id, "❌ Download timed out. Please try again.")
        return

    title      = job.get("title", "Reel")
    video_path = job.get("video_path")
    audio_path = job.get("audio_path")
    video_url  = job.get("video_url")
    audio_url  = job.get("audio_url")

    MAX = 50 * 1024 * 1024
    from pathlib import Path

    async def send_file(path_str, fallback_url, send_fn, caption, extra):
        path = Path(path_str)
        if not path.exists():
            return False
        if path.stat().st_size <= MAX:
            try:
                with open(path, "rb") as fh:
                    await getattr(bot, send_fn)(
                        telegram_chat_id,
                        **{send_fn.replace("send_", ""): fh},
                        caption=caption,
                        write_timeout=300,
                        read_timeout=60,
                        **extra,
                    )
                return True
            except Exception as exc:
                logger.warning("Direct upload failed: %s", exc)
        if fallback_url:
            await bot.send_message(
                telegram_chat_id,
                f"📥 {caption}\nDownload here: {BASE_URL}{fallback_url}",
            )
        return False

    video_direct = await send_file(video_path, video_url, "send_video", f"🎬 {title}", {"supports_streaming": True})
    audio_direct = await send_file(audio_path, audio_url, "send_audio", f"🎵 {title}", {"title": title})
    cleanup_job(job_id, delete_files=(video_direct and audio_direct))


def _extract_reel_url(text: str, attachments: list) -> str | None:
    # Text message containing a reel URL
    if text:
        m = _REEL_RE.search(text)
        if m:
            return m.group(0)

    # Forwarded reel attachment (type "share")
    for att in attachments:
        if att.get("type") == "share":
            url = att.get("payload", {}).get("url", "")
            if _REEL_RE.search(url):
                return url

    return None
