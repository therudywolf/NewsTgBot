"""Telethon parser for parsing Telegram channels via MTProto Client API.

NewsTgBot - Self-hosted IT news aggregator
Copyright (C) 2026 therudywolf
Licensed under AGPL-3.0
"""
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta, timezone

from .base import BaseParser
import config

logger = logging.getLogger(__name__)


class TelethonParser(BaseParser):
    """Parser for Telegram channels using Telethon (MTProto Client API)."""
    
    def __init__(self):
        """Initialize Telethon parser."""
        super().__init__()
        self.client = None
        self._initialized = False
    
    async def _get_client(self):
        """Get or create Telethon client."""
        if self.client is not None:
            return self.client
        
        try:
            from telethon import TelegramClient
            from telethon.errors import SessionPasswordNeededError
            
            api_id = config.get_telethon_api_id()
            api_hash = config.get_telethon_api_hash()
            if not api_id or not api_hash:
                logger.warning("Telethon API credentials not configured")
                return None
            
            self.client = TelegramClient(
                config.TELETHON_SESSION_FILE,
                int(api_id),
                api_hash,
            )
            
            # Connect and authenticate if needed
            await self.client.connect()
            
            if not await self.client.is_user_authorized():
                if not config.get_telethon_phone():
                    logger.warning("Telethon phone number not configured")
                    return None
                
                phone = config.get_telethon_phone()
                await self.client.send_code_request(phone)
                logger.info(f"Telethon: Code sent to {phone}. "
                           "Please use client.sign_in() manually to complete authentication.")
                return None
            
            self._initialized = True
            return self.client
            
        except ImportError:
            logger.error("Telethon library not installed. Install with: pip install telethon")
            return None
        except Exception as e:
            logger.error(f"Error initializing Telethon client: {e}")
            return None
    
    async def check_availability(self) -> bool:
        """Check if Telethon parser is available and configured."""
        if not config.get_telethon_api_id() or not config.get_telethon_api_hash():
            return False
        
        try:
            client = await self._get_client()
            if client is None:
                return False
            
            # Check if client is connected
            return await client.is_connected()
        except Exception as e:
            logger.error(f"Error checking Telethon availability: {e}")
            return False
    
    async def get_channel_info(self, channel_username: str) -> Optional[Dict[str, Any]]:
        """
        Get information about a channel.
        
        Args:
            channel_username: Channel username (without @)
            
        Returns:
            Dict with channel info or None
        """
        try:
            client = await self._get_client()
            if client is None:
                return None
            
            username = self._entity_ref(channel_username)
            
            # Get entity (channel)
            entity = await client.get_entity(username)
            
            return {
                'channel_id': entity.id,
                'username': getattr(entity, 'username', None),
                'title': getattr(entity, 'title', None),
                'description': getattr(entity, 'about', None),
                'subscribers': getattr(entity, 'participants_count', None),
                'is_public': entity.broadcast if hasattr(entity, 'broadcast') else True
            }
        except Exception as e:
            logger.error(f"Error getting channel info via Telethon: {e}")
            return None
    
    async def parse_channel(
        self,
        channel_username: str,
        limit: Optional[int] = None,
        days: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Parse messages from a channel using Telethon.
        
        Args:
            channel_username: Channel username
            limit: Maximum number of messages to fetch
            days: Number of days to look back
            
        Returns:
            Dict with parsing results
        """
        result = {
            'parsed': 0,
            'skipped': 0,
            'errors': 0,
            'messages': []
        }
        
        try:
            client = await self._get_client()
            if client is None:
                result['errors'] = 1
                return result
            
            username = self._entity_ref(channel_username)
            
            # Get entity
            entity = await client.get_entity(username)
            channel_id = entity.id
            
            # Calculate offset date if days specified
            offset_date = None
            if days:
                offset_date = datetime.now(timezone.utc) - timedelta(days=days)
            
            # Fetch messages
            messages_fetched = 0
            async for message in client.iter_messages(entity, limit=limit):
                try:
                    # Skip if message is too old
                    message_date = message.date
                    if message_date and message_date.tzinfo is None:
                        message_date = message_date.replace(tzinfo=timezone.utc)
                    if offset_date and message_date < offset_date:
                        break
                    
                    # Get message text
                    text = message.message or message.raw_text or ""
                    if not text.strip():
                        result['skipped'] += 1
                        continue
                    
                    # Capture image attachments by Telegram file id; the
                    # channel_reader will resolve these via download_media
                    # when a pipeline actually needs the picture.
                    media: List[Dict[str, Any]] = []
                    if getattr(message, "photo", None):
                        media.append({
                            "kind": "image",
                            "url": None,
                            "telegram_message_id": message.id,
                            "telegram_channel_id": channel_id,
                        })
                    elif getattr(message, "document", None):
                        mime = getattr(message.document, "mime_type", "") or ""
                        if mime.startswith("image/"):
                            media.append({
                                "kind": "image",
                                "url": None,
                                "mime": mime,
                                "telegram_message_id": message.id,
                                "telegram_channel_id": channel_id,
                            })

                    # Format message
                    msg_dict = {
                        'message_id': message.id,
                        'text': text,
                        'date': self._format_date(message.date),
                        'channel_id': channel_id,
                        'media': media,
                    }
                    
                    result['messages'].append(msg_dict)
                    result['parsed'] += 1
                    messages_fetched += 1
                    
                    # Log progress every 100 messages
                    if messages_fetched % 100 == 0:
                        logger.info(f"Telethon: Parsed {messages_fetched} messages from {channel_username}")
                    
                except Exception as e:
                    logger.error(f"Error processing message {message.id}: {e}")
                    result['errors'] += 1
                    continue
            
            logger.info(f"Telethon: Completed parsing {channel_username}. "
                       f"Parsed: {result['parsed']}, Skipped: {result['skipped']}, Errors: {result['errors']}")
            
            return result
            
        except Exception as e:
            logger.error(f"Error parsing channel {channel_username} via Telethon: {e}", exc_info=True)
            result['errors'] += 1
            return result
    
    async def disconnect(self):
        """Disconnect Telethon client."""
        if self.client:
            try:
                await self.client.disconnect()
            except Exception:
                pass
            self.client = None
            self._initialized = False

    def _entity_ref(self, channel_username: str):
        """Return an entity reference accepted by Telethon."""
        normalized = self._normalize_channel_username(str(channel_username))
        if normalized.lstrip("-").isdigit():
            return int(normalized)
        return normalized

