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
        # #region agent log
        import json; f = open('c:\\Users\\rudywolf\\Workspace\\NewsTgBot\\.cursor\\debug.log', 'a', encoding='utf-8'); f.write(json.dumps({"sessionId": "debug-session", "runId": "run1", "hypothesisId": "D", "location": "channel_reader.py:20", "message": "process_channel_message entry", "data": {"message_id": message.message_id if message else None, "has_chat": message.chat is not None if message else False, "chat_type": str(message.chat.type) if message and message.chat else None}, "timestamp": int(__import__('time').time() * 1000)}) + '\n'); f.close()
        # #endregion
        
        try:
            # Check if message is from a channel
            if not message.chat or message.chat.type not in [ChatType.CHANNEL, ChatType.SUPERGROUP]:
                # #region agent log
                f = open('c:\\Users\\rudywolf\\Workspace\\NewsTgBot\\.cursor\\debug.log', 'a', encoding='utf-8'); f.write(json.dumps({"sessionId": "debug-session", "runId": "run1", "hypothesisId": "D", "location": "channel_reader.py:30", "message": "process_channel_message: not channel/supergroup", "data": {"chat_type": str(message.chat.type) if message and message.chat else None}, "timestamp": int(__import__('time').time() * 1000)}) + '\n'); f.close()
                # #endregion
                return False
            
            # Get channel ID
            channel_id = message.chat.id
            
            # #region agent log
            f = open('c:\\Users\\rudywolf\\Workspace\\NewsTgBot\\.cursor\\debug.log', 'a', encoding='utf-8'); f.write(json.dumps({"sessionId": "debug-session", "runId": "run1", "hypothesisId": "D", "location": "channel_reader.py:34", "message": "process_channel_message: checking channel", "data": {"channel_id": channel_id}, "timestamp": int(__import__('time').time() * 1000)}) + '\n'); f.close()
            # #endregion
            
            # Check if this channel is in our database
            channel_info = self.db.get_channel_by_id(channel_id)
            
            # #region agent log
            f = open('c:\\Users\\rudywolf\\Workspace\\NewsTgBot\\.cursor\\debug.log', 'a', encoding='utf-8'); f.write(json.dumps({"sessionId": "debug-session", "runId": "run1", "hypothesisId": "D", "location": "channel_reader.py:40", "message": "process_channel_message: channel_info check", "data": {"channel_id": channel_id, "channel_info_found": channel_info is not None}, "timestamp": int(__import__('time').time() * 1000)}) + '\n'); f.close()
            # #endregion
            
            if not channel_info:
                # Channel not tracked, skip
                # #region agent log
                f = open('c:\\Users\\rudywolf\\Workspace\\NewsTgBot\\.cursor\\debug.log', 'a', encoding='utf-8'); f.write(json.dumps({"sessionId": "debug-session", "runId": "run1", "hypothesisId": "D", "location": "channel_reader.py:44", "message": "process_channel_message: channel not tracked", "data": {"channel_id": channel_id}, "timestamp": int(__import__('time').time() * 1000)}) + '\n'); f.close()
                # #endregion
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
            
            # #region agent log
            f = open('c:\\Users\\rudywolf\\Workspace\\NewsTgBot\\.cursor\\debug.log', 'a', encoding='utf-8'); f.write(json.dumps({"sessionId": "debug-session", "runId": "run1", "hypothesisId": "D", "location": "channel_reader.py:54", "message": "process_channel_message: news added", "data": {"channel_id": channel_id, "message_id": message_id, "news_id": news_id, "text_length": len(text)}, "timestamp": int(__import__('time').time() * 1000)}) + '\n'); f.close()
            # #endregion
            
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
            source_config = self.db.get_channel_source_config(channel_id) or {}
            
            logger.info(f"Starting force parse for channel {channel_username} (ID: {channel_id}, "
                       f"source: {source_type}, limit={limit}, days={days})")
            
            # Get latest news date to avoid duplicates
            latest_date = self.db.get_latest_news_date(channel_id) if channel_id else None
            
            # Use parser manager for non-telegram_bot sources
            if source_type != 'telegram_bot':
                # Normalize username
                username = channel_username
                if username and not username.startswith('http'):
                    username = username.lstrip('@')
                
                # Parse using appropriate parser
                parse_result = await self.parser_manager.parse_channel(
                    username,
                    source_type=source_type,
                    limit=limit,
                    days=days,
                    fallback=True
                )
                
                # Store parsed messages
                for msg in parse_result.get('messages', []):
                    try:
                        # Skip if we already have this message
                        if latest_date and msg['date'] <= latest_date:
                            stats['skipped'] += 1
                            continue
                        
                        # Use channel_id from message or from database
                        msg_channel_id = msg.get('channel_id', channel_id)
                        if not msg_channel_id:
                            msg_channel_id = channel_id
                        
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
                # Legacy: Use bot API (requires bot to be admin)
                if not bot:
                    logger.warning("Bot instance required for telegram_bot source type")
                    stats['errors'] = 1
                    return stats
                
                # Get chat object
                chat = await bot.get_chat(channel_id)
                
                # Calculate date limit if days specified
                from datetime import timedelta
                offset_date = None
                if days:
                    offset_date = datetime.now() - timedelta(days=days)
                
                # Fetch messages
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
                    logger.warning(f"get_chat_history not available for channel {channel_id}. "
                                 "Channel history can only be parsed from incoming updates.")
                    stats['errors'] += 1
                except Exception as e:
                    logger.error(f"Error fetching chat history: {e}")
                    stats['errors'] += 1
            
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

