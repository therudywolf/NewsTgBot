"""RSS parser for parsing news from RSS feeds.

NewsTgBot - Self-hosted IT news aggregator
Copyright (C) 2026 therudywolf
Licensed under AGPL-3.0
"""
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import aiohttp
import asyncio

from .base import BaseParser
import config
from source_identity import stable_source_id

logger = logging.getLogger(__name__)


class RSSParser(BaseParser):
    """Parser for RSS feeds."""
    
    def __init__(self):
        """Initialize RSS parser."""
        super().__init__()
    
    async def check_availability(self) -> bool:
        """Check if RSS parser is available."""
        try:
            import feedparser
            return True
        except ImportError:
            logger.error("feedparser library not installed. Install with: pip install feedparser")
            return False
    
    def _get_rss_url(self, channel_username: str) -> Optional[str]:
        """
        Get RSS URL for a channel.
        Common patterns:
        - t.me/channelname/rss
        - channel RSS feed URL (if provided in source_config)
        
        Args:
            channel_username: Channel identifier
            
        Returns:
            RSS URL or None
        """
        username = self._normalize_channel_username(channel_username)
        
        # Common Telegram RSS pattern
        rss_url = f"https://t.me/s/{username}/rss"
        return rss_url
    
    async def _fetch_rss(self, url: str) -> Optional[Any]:
        """
        Fetch and parse RSS feed.
        
        Args:
            url: RSS feed URL
            
        Returns:
            Parsed feed object or None
        """
        try:
            import feedparser
            
            timeout = aiohttp.ClientTimeout(total=config.RSS_PARSER_TIMEOUT)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as response:
                    if response.status != 200:
                        logger.warning(f"RSS feed returned status {response.status} for {url}")
                        return None
                    
                    content = await response.text()
                    
                    # Parse RSS feed
                    feed = feedparser.parse(content)
                    
                    if feed.bozo and feed.bozo_exception:
                        logger.warning(f"RSS parsing error for {url}: {feed.bozo_exception}")
                        return None
                    
                    return feed
                    
        except ImportError:
            logger.error("feedparser library not installed")
            return None
        except asyncio.TimeoutError:
            logger.error(f"Timeout fetching RSS feed: {url}")
            return None
        except Exception as e:
            logger.error(f"Error fetching RSS feed {url}: {e}")
            return None
    
    async def get_channel_info(self, channel_username: str) -> Optional[Dict[str, Any]]:
        """
        Get information about a channel from RSS feed.
        
        Args:
            channel_username: Channel username or RSS URL
            
        Returns:
            Dict with channel info or None
        """
        try:
            # Determine RSS URL
            if channel_username.startswith('http://') or channel_username.startswith('https://'):
                rss_url = channel_username
            else:
                rss_url = self._get_rss_url(channel_username)
            
            feed = await self._fetch_rss(rss_url)
            if not feed or not hasattr(feed, 'feed'):
                return None
            
            feed_info = feed.feed
            
            return {
                'channel_id': None,  # RSS doesn't have channel_id
                'username': channel_username,
                'title': feed_info.get('title', channel_username),
                'description': feed_info.get('description', ''),
                'subscribers': None,
                'is_public': True
            }
        except Exception as e:
            logger.error(f"Error getting RSS channel info: {e}")
            return None
    
    async def parse_channel(
        self,
        channel_username: str,
        limit: Optional[int] = None,
        days: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Parse messages from an RSS feed.
        
        Args:
            channel_username: Channel username or RSS URL
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
            # Determine RSS URL
            if channel_username.startswith('http://') or channel_username.startswith('https://'):
                rss_url = channel_username
                channel_id = stable_source_id(channel_username, "rss")
            else:
                rss_url = self._get_rss_url(channel_username)
                channel_id = stable_source_id(channel_username, "rss")
            
            # Fetch RSS feed
            feed = await self._fetch_rss(rss_url)
            if not feed or not hasattr(feed, 'entries'):
                result['errors'] = 1
                return result
            
            # Calculate cutoff date if days specified
            cutoff_date = None
            if days:
                cutoff_date = datetime.now() - timedelta(days=days)
            
            # Process entries
            entries = feed.entries[:limit] if limit else feed.entries
            messages_fetched = 0
            
            for entry in entries:
                try:
                    # Parse date
                    entry_date = None
                    if hasattr(entry, 'published_parsed') and entry.published_parsed:
                        entry_date = datetime(*entry.published_parsed[:6])
                    elif hasattr(entry, 'updated_parsed') and entry.updated_parsed:
                        entry_date = datetime(*entry.updated_parsed[:6])
                    else:
                        entry_date = datetime.now()
                    
                    # Skip if too old
                    if cutoff_date and entry_date < cutoff_date:
                        continue
                    
                    title = entry.get('title', '').strip()
                    summary = entry.get('summary') or entry.get('description') or ''
                    link = entry.get('link', '').strip()

                    # Clean HTML tags if present
                    import re
                    summary = re.sub(r'<[^>]+>', '', summary).strip()

                    text_parts = []
                    if title:
                        text_parts.append(title)
                    if summary and summary.lower() not in {title.lower(), 'comments'}:
                        text_parts.append(summary)
                    if link:
                        text_parts.append(f"Source: {link}")

                    text = "\n".join(text_parts).strip()
                    
                    if not text:
                        result['skipped'] += 1
                        continue
                    
                    # Generate message_id from entry link or title hash
                    message_id = stable_source_id(entry.get('link', entry.get('title', str(entry_date))), "rss-message")
                    
                    # Format message
                    msg_dict = {
                        'message_id': message_id,
                        'text': text,
                        'date': self._format_date(entry_date),
                        'channel_id': channel_id
                    }
                    
                    result['messages'].append(msg_dict)
                    result['parsed'] += 1
                    messages_fetched += 1
                    
                except Exception as e:
                    logger.error(f"Error processing RSS entry: {e}")
                    result['errors'] += 1
                    continue
            
            logger.info(f"RSS: Completed parsing {rss_url}. "
                       f"Parsed: {result['parsed']}, Skipped: {result['skipped']}, Errors: {result['errors']}")
            
            return result
            
        except Exception as e:
            logger.error(f"Error parsing RSS feed {channel_username}: {e}", exc_info=True)
            result['errors'] += 1
            return result
