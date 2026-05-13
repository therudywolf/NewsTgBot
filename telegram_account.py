"""Telegram user-account integration for selecting and parsing channels.

NewsTgBot - Self-hosted IT news aggregator
Copyright (C) 2026 therudywolf
Licensed under AGPL-3.0
"""
import logging
from typing import Any, Dict, List, Optional

import config

logger = logging.getLogger(__name__)


class TelegramAccountService:
    """Small wrapper around Telethon login and channel discovery."""

    def __init__(self):
        self.client = None

    def is_configured(self) -> bool:
        return bool(config.get_telethon_api_id() and config.get_telethon_api_hash())

    async def get_client(self):
        if not self.is_configured():
            raise RuntimeError("TELETHON_API_ID and TELETHON_API_HASH are not configured")

        if self.client is not None:
            if not self.client.is_connected():
                await self.client.connect()
            return self.client

        from telethon import TelegramClient

        self.client = TelegramClient(
            config.TELETHON_SESSION_FILE,
            int(config.get_telethon_api_id()),
            config.get_telethon_api_hash(),
        )
        await self.client.connect()
        return self.client

    async def status(self) -> Dict[str, Any]:
        if not self.is_configured():
            return {
                "configured": False,
                "connected": False,
                "authorized": False,
                "session_file": config.TELETHON_SESSION_FILE,
            }

        try:
            client = await self.get_client()
            authorized = await client.is_user_authorized()
            user = None
            if authorized:
                me = await client.get_me()
                user = {
                    "id": me.id,
                    "username": me.username,
                    "first_name": me.first_name,
                    "phone": me.phone,
                }
            return {
                "configured": True,
                "connected": client.is_connected(),
                "authorized": authorized,
                "session_file": config.TELETHON_SESSION_FILE,
                "user": user,
            }
        except Exception as e:
            logger.error("Telegram account status failed: %s", e)
            return {
                "configured": True,
                "connected": False,
                "authorized": False,
                "session_file": config.TELETHON_SESSION_FILE,
                "error": str(e),
            }

    async def send_code(self, phone: str) -> Dict[str, Any]:
        client = await self.get_client()
        sent = await client.send_code_request(phone)
        return {
            "phone": phone,
            "phone_code_hash": getattr(sent, "phone_code_hash", None),
            "type": sent.type.__class__.__name__ if getattr(sent, "type", None) else None,
        }

    async def sign_in(
        self,
        phone: str,
        code: str,
        password: Optional[str] = None,
        phone_code_hash: Optional[str] = None,
    ) -> Dict[str, Any]:
        from telethon.errors import SessionPasswordNeededError

        client = await self.get_client()
        try:
            await client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
        except SessionPasswordNeededError:
            if not password:
                return {"authorized": False, "password_required": True}
            await client.sign_in(password=password)

        authorized = await client.is_user_authorized()
        return {"authorized": authorized, "password_required": False}

    async def list_channels(self, limit: int = 300) -> List[Dict[str, Any]]:
        client = await self.get_client()
        if not await client.is_user_authorized():
            raise RuntimeError("Telegram account is not authorized")

        channels: List[Dict[str, Any]] = []
        async for dialog in client.iter_dialogs(limit=limit):
            entity = dialog.entity
            is_channel = bool(getattr(entity, "broadcast", False) or getattr(entity, "megagroup", False))
            if not is_channel:
                continue

            channels.append(
                {
                    "id": entity.id,
                    "username": getattr(entity, "username", None),
                    "title": getattr(entity, "title", dialog.name),
                    "megagroup": bool(getattr(entity, "megagroup", False)),
                    "broadcast": bool(getattr(entity, "broadcast", False)),
                }
            )

        channels.sort(key=lambda item: (item["title"] or "").lower())
        return channels

    async def disconnect(self):
        if self.client:
            await self.client.disconnect()
            self.client = None
