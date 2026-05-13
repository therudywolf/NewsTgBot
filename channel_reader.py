"""Channel reader for fetching messages from Telegram channels."""
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime
from telegram import Update, Message
from telegram.constants import ChatType
from telegram.ext import ContextTypes
import database
from parsers.parser_manager import ParserManager

logger = logging.getLogger(__name__)


class ChannelReader:
    """Service for reading messages from Telegram channels."""
    
    def __init__(self, db: database.Database = None):
        """Initialize channel reader."""
        self.db = db or database.Database()
        self.parser_manager = ParserManager()
    
    async def process_channel_message(
        self,
        message: Message
    ) -> bool:
        """Process a single message from a channel."""
        try:
            # Check if message is from a channel
            if not message.chat or message.chat.type not in [ChatType.CHANNEL, ChatType.SUPERGROUP]:
                return False
            
            # Get channel ID
            channel_id = message.chat.id
            
            # Check if this channel is in our database
            channel_info = self.db.get_channel_by_id(channel_id)
            
            if not channel_info:
                # Channel not tracked, skip
                return False
            
            # Get message text
            text = message.text or message.caption or ""
            if not text.strip():
                # Skip messages without text
                return False
            
            # Store the message in the database
            message_id = message.message_id
            date = message.date
            date_str = date.isoformat() if isinstance(date, datetime) else str(date)
            
            news_id = self.db.add_news(channel_id, message_id, text, date_str)
            # Note: Tag generation can be done asynchronously in background task

            return news_id is not None
            
        except Exception as e:
            logger.error(f"Error processing message {message.message_id if message else 'unknown'} from channel: {e}")
            return False
    
    def is_tracked_channel(self, channel_id: int) -> bool:
        """Check if a channel is being tracked."""
        return self.db.get_channel_by_id(channel_id) is not None
    
    async def force_parse_channel(
        self, 
        bot=None, 
        channel_id: int = None, 
        channel_username: str = None,
        limit: int = None, 
        days: int = None
    ) -> Dict[str, Any]:
        """
        Force parse channel history using appropriate parser.
        
        Args:
            bot: Telegram bot instance (optional, for legacy telegram_bot source type)
            channel_id: Channel ID to parse (optional if channel_username provided)
            channel_username: Channel username to parse (optional if channel_id provided)
            limit: Maximum number of messages to fetch (None = all)
            days: Number of days to look back (None = all)
            
        Returns:
            Dict with stats: {'parsed': int, 'skipped': int, 'errors': int}
        """
        stats = {'parsed': 0, 'skipped': 0, 'errors': 0}
        
        try:
            # Determine channel identifier
            channel_info = None
            if channel_id:
                channel_info = self.db.get_channel_by_id(channel_id)
                if not channel_info:
                    logger.warning(f"Channel {channel_id} is not tracked")
                    return stats
                channel_username = channel_info.get('username') or str(channel_id)
            
            if not channel_info and channel_username:
                # Try to find channel by username
                all_channels = self.db.get_all_channels()
                for ch in all_channels:
                    if ch.get('username') == channel_username or str(ch.get('channel_id')) == str(channel_username):
                        channel_info = ch
                        channel_id = ch.get('channel_id')
                        break
            
            if not channel_info:
                logger.warning(f"Channel {channel_username or channel_id} not found")
                return stats
            
            # Get source type
            source_type = channel_info.get('source_type', 'telegram_bot')
            source_config_data = self.db.get_channel_source_config(channel_id)
            source_config = source_config_data.get('source_config', {}) if source_config_data else {}
            
            logger.info(f"Starting force parse for channel {channel_username} (ID: {channel_id}, "
                       f"source: {source_type}, limit={limit}, days={days})")
            
            # Get latest news date to avoid duplicates
            latest_date = self.db.get_latest_news_date(channel_id) if channel_id else None
            
            # Use parser manager for non-telegram_bot sources
            if source_type != 'telegram_bot':
                # For RSS sources, use rss_url from source_config if available
                username = channel_username
                if source_type == 'rss' and source_config and isinstance(source_config, dict):
                    rss_url = source_config.get('rss_url')
                    if rss_url:
                        username = rss_url
                
                # Normalize username (don't strip @ if it's a URL)
                if username and not username.startswith('http'):
                    username = username.lstrip('@')
                
                # Parse using appropriate parser
                parse_result = await self.parser_manager.parse_channel(
                    username,
                    source_type=source_type,
                    limit=limit,
                    days=days,
                    fallback=False
                )
                
                # Store parsed messages
                for msg in parse_result.get('messages', []):
                    try:
                        # Skip if we already have this message
                        if latest_date and msg['date'] <= latest_date:
                            stats['skipped'] += 1
                            continue
                        
                        # Store messages under the configured source ID so joins
                        # and stats stay consistent for pseudo-ID sources.
                        msg_channel_id = channel_id or msg.get('channel_id')
                        
                        news_id = self.db.add_news(
                            msg_channel_id,
                            msg['message_id'],
                            msg['text'],
                            msg['date']
                        )
                        
                        if news_id:
                            stats['parsed'] += 1
                        else:
                            stats['skipped'] += 1
                    except Exception as e:
                        logger.error(f"Error storing message: {e}")
                        stats['errors'] += 1
                
                stats['errors'] += parse_result.get('errors', 0)
                stats['skipped'] += parse_result.get('skipped', 0)
                
            else:
                # telegram_bot source type: the Bot API does not expose
                # message history iteration.  News are captured in real-time
                # via channel_post updates.  For historical parsing, switch
                # the source to 'telethon', 'rss', or 'web'.
                logger.info(
                    f"Channel {channel_id} uses telegram_bot source type. "
                    "Historical parsing is not available via Bot API — "
                    "news are captured from live channel_post updates only."
                )
            
            logger.info(f"Force parse completed for channel {channel_username or channel_id}: {stats}")
            return stats
            
        except Exception as e:
            logger.error(f"Error in force_parse_channel: {e}", exc_info=True)
            stats['errors'] += 1
            return stats
    
    async def get_available_parsers(self) -> List[str]:
        """
        Get list of available parsers.
        
        Returns:
            List of available parser type names
        """
        return await self.parser_manager.get_available_parsers()
