"""Instagram Graph API helpers — send DMs and check follower status."""

import logging

import httpx

from ..config import IG_PAGE_ACCESS_TOKEN

logger = logging.getLogger(__name__)

_API = "https://graph.facebook.com/v21.0"


async def get_user_info(igsid: str) -> dict:
    """Fetch basic profile + follower status for a sender IGSID."""
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(
            f"{_API}/{igsid}",
            params={
                "fields": "id,name,username,is_user_follow_business",
                "access_token": IG_PAGE_ACCESS_TOKEN,
            },
        )
    data = r.json()
    if "error" in data:
        logger.warning("get_user_info error for %s: %s", igsid, data["error"])
    return data


async def send_message(igsid: str, text: str) -> bool:
    """Send a text DM to a user. Returns True on success."""
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            f"{_API}/me/messages",
            params={"access_token": IG_PAGE_ACCESS_TOKEN},
            json={
                "recipient": {"id": igsid},
                "message": {"text": text},
                "messaging_type": "RESPONSE",
            },
        )
    ok = r.status_code == 200
    if not ok:
        logger.warning("send_message failed for %s: %s", igsid, r.text)
    return ok


def is_follower(user_info: dict) -> bool:
    """Return True if the user follows the business account."""
    return bool(user_info.get("is_user_follow_business"))
