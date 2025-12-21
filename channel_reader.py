"""Channel reader for fetching messages from Telegram channels."""
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime
from telegram import Update, Message
from telegram.constants import ChatType
from telegram.ext import ContextTypes
import database

logger = logging.getLogger(__name__)


class ChannelReader:
    """Service for reading messages from Telegram channels."""
    
    def __init__(self, db: database.Database = None):
        """Initialize channel reader."""
        self.db = db or database.Database()
    
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
    
    async def force_parse_channel(self, bot, channel_id: int, limit: int = None, days: int = None) -> Dict[str, Any]:
        """
        Force parse channel history.
        
        Args:
            bot: Telegram bot instance
            channel_id: Channel ID to parse
            limit: Maximum number of messages to fetch (None = all)
            days: Number of days to look back (None = all)
            
        Returns:
            Dict with stats: {'parsed': int, 'skipped': int, 'errors': int}
        """
        stats = {'parsed': 0, 'skipped': 0, 'errors': 0}
        
        try:
            # Check if channel is tracked
            channel_info = self.db.get_channel_by_id(channel_id)
            if not channel_info:
                logger.warning(f"Channel {channel_id} is not tracked")
                return stats
            
            # Get chat object
            chat = await bot.get_chat(channel_id)
            
            # Calculate date limit if days specified
            from datetime import timedelta
            offset_date = None
            if days:
                offset_date = datetime.now() - timedelta(days=days)
            
            logger.info(f"Starting force parse for channel {channel_id} (limit={limit}, days={days})")
            
            # Get latest news date to avoid duplicates
            latest_date = self.db.get_latest_news_date(channel_id)
            
            # Fetch messages
            # Note: Telegram Bot API doesn't support getting full chat history for channels
            # This method works for groups/supergroups where bot is a member
            messages_fetched = 0
            try:
                async for message in bot.get_chat_history(chat.id, limit=limit):
                    try:
                        # Skip if message is too old
                        if offset_date and message.date < offset_date:
                            break
                        
                        # Skip if we already have this message (by date check)
                        if latest_date and message.date.isoformat() <= latest_date:
                            continue
                        
                        # Get message text
                        text = message.text or message.caption or ""
                        if not text.strip():
                            stats['skipped'] += 1
                            continue
                        
                        # Store the message
                        message_id = message.message_id
                        date_str = message.date.isoformat()
                        
                        news_id = self.db.add_news(channel_id, message_id, text, date_str)
                        if news_id:
                            stats['parsed'] += 1
                            messages_fetched += 1
                        else:
                            stats['skipped'] += 1
                            
                        # Log progress every 100 messages
                        if messages_fetched % 100 == 0:
                            logger.info(f"Parsed {messages_fetched} messages from channel {channel_id}")
                            
                    except Exception as e:
                        logger.error(f"Error processing message {message.message_id}: {e}")
                        stats['errors'] += 1
                        continue
            except AttributeError:
                # get_chat_history may not be available in this version
                logger.warning(f"get_chat_history not available for channel {channel_id}. "
                             "Channel history can only be parsed from incoming updates.")
                stats['errors'] += 1
            except Exception as e:
                logger.error(f"Error fetching chat history: {e}")
                stats['errors'] += 1
            
            logger.info(f"Force parse completed for channel {channel_id}: {stats}")
            return stats
            
        except Exception as e:
            logger.error(f"Error in force_parse_channel for {channel_id}: {e}", exc_info=True)
            stats['errors'] += 1
            return stats

