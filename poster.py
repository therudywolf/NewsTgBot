"""Posting service: publish text to Telegram via Bot API or user account.

NewsTgBot - Self-hosted IT news aggregator
Licensed under AGPL-3.0
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import aiohttp

logger = logging.getLogger(__name__)


class PostingError(RuntimeError):
    """Raised when a publish attempt fails."""


async def send_via_bot_api(
    token: str,
    chat_id: str,
    text: str,
    parse_mode: Optional[str] = None,
    disable_web_page_preview: bool = True,
) -> Dict[str, Any]:
    """Publish *text* to *chat_id* through the Telegram Bot API."""
    if not token:
        raise PostingError("Bot token is not configured")
    if not chat_id:
        raise PostingError("Target chat id is required")
    if not text or not text.strip():
        raise PostingError("Empty post text")

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload: Dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": disable_web_page_preview,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode

    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(url, json=payload) as response:
            data = await response.json(content_type=None)
            if response.status >= 400 or not data.get("ok"):
                raise PostingError(
                    f"Bot API error {response.status}: {data.get('description') or data}"
                )
            return data.get("result", {})


async def send_photo_via_bot_api(
    token: str,
    chat_id: str,
    photo_url: str,
    caption: Optional[str] = None,
    parse_mode: Optional[str] = None,
) -> Dict[str, Any]:
    """Publish *photo_url* to *chat_id* via Bot API sendPhoto.

    Captions are limited to 1024 chars; longer text is split off and sent
    as a separate reply message so it isn't silently truncated.
    """
    if not token:
        raise PostingError("Bot token is not configured")
    if not chat_id:
        raise PostingError("Target chat id is required")
    if not photo_url:
        raise PostingError("Photo URL is required")

    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    caption_for_photo = (caption or "")[:1024] or None
    payload: Dict[str, Any] = {
        "chat_id": chat_id,
        "photo": photo_url,
    }
    if caption_for_photo:
        payload["caption"] = caption_for_photo
    if parse_mode:
        payload["parse_mode"] = parse_mode

    timeout = aiohttp.ClientTimeout(total=60)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(url, json=payload) as response:
            data = await response.json(content_type=None)
            if response.status >= 400 or not data.get("ok"):
                raise PostingError(
                    f"Bot API sendPhoto error {response.status}: {data.get('description') or data}"
                )
            result = data.get("result", {})

    # If the caption was truncated, follow up with the rest as a reply.
    if caption and len(caption) > 1024:
        try:
            extra = caption[1024:]
            await send_via_bot_api(
                token=token,
                chat_id=chat_id,
                text=extra,
                parse_mode=parse_mode,
                disable_web_page_preview=True,
            )
        except PostingError as exc:  # noqa: BLE001 — best-effort follow-up
            logger.warning("Photo follow-up failed: %s", exc)

    return result


async def send_via_telethon(
    telegram_account_service,
    chat_id: str,
    text: str,
    link_preview: bool = False,
) -> Dict[str, Any]:
    """Publish *text* through the logged-in user account (Telethon)."""
    client = await telegram_account_service.get_client()
    if not await client.is_user_authorized():
        raise PostingError("Telegram account is not authorized")

    entity_id: Any = chat_id
    if isinstance(entity_id, str):
        stripped = entity_id.strip()
        if stripped.lstrip("-").isdigit():
            entity_id = int(stripped)
        else:
            entity_id = stripped.lstrip("@") or stripped

    try:
        message = await client.send_message(entity_id, text, link_preview=link_preview)
    except Exception as exc:  # noqa: BLE001 — surface Telethon error to user
        raise PostingError(f"Telethon send_message failed: {exc}") from exc

    return {
        "id": getattr(message, "id", None),
        "chat_id": getattr(getattr(message, "chat", None), "id", None),
        "date": getattr(message, "date", None).isoformat() if getattr(message, "date", None) else None,
    }
