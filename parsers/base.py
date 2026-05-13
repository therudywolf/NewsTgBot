"""Base parser class for all news source parsers.

NewsTgBot - Self-hosted IT news aggregator
Copyright (C) 2026 therudywolf
Licensed under AGPL-3.0
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from datetime import datetime


class BaseParser(ABC):
    """Abstract base class for all parsers."""
    
    def __init__(self):
        """Initialize the parser."""
        self.parser_type = self.__class__.__name__.lower().replace('parser', '')
    
    @abstractmethod
    async def parse_channel(
        self,
        channel_username: str,
        limit: Optional[int] = None,
        days: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Parse messages from a channel.
        
        Args:
            channel_username: Username or identifier of the channel (e.g., 'channelname' or full URL)
            limit: Maximum number of messages to fetch (None = all available)
            days: Number of days to look back (None = all available)
            
        Returns:
            Dict with structure:
            {
                'parsed': int,      # Number of successfully parsed messages
                'skipped': int,     # Number of skipped messages
                'errors': int,      # Number of errors
                'messages': List[Dict]  # List of parsed messages with structure:
                                        # {
                                        #   'message_id': int,
                                        #   'text': str,
                                        #   'date': datetime or ISO string,
                                        #   'channel_id': int (if available)
                                        # }
            }
        """
        pass
    
    @abstractmethod
    async def get_channel_info(self, channel_username: str) -> Optional[Dict[str, Any]]:
        """
        Get information about a channel.
        
        Args:
            channel_username: Username or identifier of the channel
            
        Returns:
            Dict with channel info:
            {
                'channel_id': int,     # Channel ID (if available)
                'username': str,       # Channel username
                'title': str,          # Channel title
                'description': str,    # Channel description (optional)
                'subscribers': int,    # Number of subscribers (optional)
                'is_public': bool      # Whether channel is public
            }
            or None if channel not found
        """
        pass
    
    @abstractmethod
    async def check_availability(self) -> bool:
        """
        Check if the parser is available and properly configured.
        
        Returns:
            True if parser is ready to use, False otherwise
        """
        pass
    
    def _normalize_channel_username(self, channel_username: str) -> str:
        """
        Normalize channel username by removing common prefixes.
        
        Args:
            channel_username: Channel identifier (can be URL, @username, or plain username)
            
        Returns:
            Normalized username without @, https://t.me/, etc.
        """
        username = channel_username.strip()
        
        # Remove https://t.me/ prefix
        if username.startswith('https://t.me/'):
            username = username.replace('https://t.me/', '')
        # Remove http://t.me/ prefix
        elif username.startswith('http://t.me/'):
            username = username.replace('http://t.me/', '')
        # Remove t.me/ prefix
        elif username.startswith('t.me/'):
            username = username.replace('t.me/', '')
        
        # Remove @ prefix
        if username.startswith('@'):
            username = username[1:]
        
        # Remove leading slash if present
        if username.startswith('/'):
            username = username[1:]
        
        return username
    
    def _format_date(self, date_obj) -> str:
        """
        Convert date object to ISO format string.
        
        Args:
            date_obj: datetime object or ISO string
            
        Returns:
            ISO format string
        """
        if isinstance(date_obj, str):
            return date_obj
        elif isinstance(date_obj, datetime):
            return date_obj.isoformat()
        else:
            try:
                return datetime.fromisoformat(str(date_obj)).isoformat()
            except (ValueError, TypeError):
                return datetime.now().isoformat()

