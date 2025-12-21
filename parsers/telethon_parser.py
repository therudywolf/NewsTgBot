"""Telethon parser for parsing Telegram channels via MTProto Client API."""
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta

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
            
            # Check if credentials are configured
            if not config.TELETHON_API_ID or not config.TELETHON_API_HASH:
                logger.warning("Telethon API credentials not configured")
                return None
            
            # Create client
            self.client = TelegramClient(
                config.TELETHON_SESSION_FILE,
                int(config.TELETHON_API_ID),
                config.TELETHON_API_HASH
            )
            
            # Connect and authenticate if needed
            await self.client.connect()
            
            if not await self.client.is_user_authorized():
                if not config.TELETHON_PHONE:
                    logger.warning("Telethon phone number not configured")
                    return None
                
                await self.client.send_code_request(config.TELETHON_PHONE)
                logger.info(f"Telethon: Code sent to {config.TELETHON_PHONE}. "
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
        if not config.TELETHON_API_ID or not config.TELETHON_API_HASH:
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
            
            username = self._normalize_channel_username(channel_username)
            
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
            
            username = self._normalize_channel_username(channel_username)
            
            # Get entity
            entity = await client.get_entity(username)
            channel_id = entity.id
            
            # Calculate offset date if days specified
            offset_date = None
            if days:
                offset_date = datetime.now() - timedelta(days=days)
            
            # Fetch messages
            messages_fetched = 0
            async for message in client.iter_messages(entity, limit=limit):
                try:
                    # Skip if message is too old
                    if offset_date and message.date < offset_date:
                        break
                    
                    # Get message text
                    text = message.message or message.raw_text or ""
                    if not text.strip():
                        result['skipped'] += 1
                        continue
                    
                    # Format message
                    msg_dict = {
                        'message_id': message.id,
                        'text': text,
                        'date': self._format_date(message.date),
                        'channel_id': channel_id
                    }
                    
                    result['messages'].append(msg_dict)
                    result['parsed'] += 1
                    messages_fetched += 1
                    
                    # Log progress every 100 messages
                    if messages_fetched % 100 == 0:
                        logger.info(f"Telethon: Parsed {messages_fetched} messages from {username}")
                    
                except Exception as e:
                    logger.error(f"Error processing message {message.id}: {e}")
                    result['errors'] += 1
                    continue
            
            logger.info(f"Telethon: Completed parsing {username}. "
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
            except:
                pass
            self.client = None
            self._initialized = False

