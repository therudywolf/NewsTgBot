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
            
            return self.db.add_news(channel_id, message_id, text, date_str)
            
        except Exception as e:
            logger.error(f"Error processing message {message.message_id if message else 'unknown'} from channel: {e}")
            return False
    
    def is_tracked_channel(self, channel_id: int) -> bool:
        """Check if a channel is being tracked."""
        return self.db.get_channel_by_id(channel_id) is not None

