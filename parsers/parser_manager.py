"""Parser manager for coordinating all parsers.

NewsTgBot - Self-hosted IT news aggregator
Copyright (C) 2026 therudywolf
Licensed under AGPL-3.0
"""
import logging
from typing import List, Dict, Any, Optional
from .base import BaseParser
from .telethon_parser import TelethonParser
from .rss_parser import RSSParser
from .web_parser import WebParser
import config

logger = logging.getLogger(__name__)


class ParserManager:
    """Manager for coordinating all parsers with fallback mechanism."""
    
    def __init__(self):
        """Initialize parser manager."""
        self.parsers: Dict[str, BaseParser] = {}
        self._init_parsers()
    
    def _init_parsers(self):
        """Initialize all available parsers."""
        # Initialize parsers based on priority
        parser_classes = {
            'telethon': TelethonParser,
            'rss': RSSParser,
            'web': WebParser
        }
        
        for parser_type in config.get_parser_priority():
            if parser_type in parser_classes:
                try:
                    parser = parser_classes[parser_type]()
                    self.parsers[parser_type] = parser
                    logger.info(f"Initialized {parser_type} parser")
                except Exception as e:
                    logger.warning(f"Failed to initialize {parser_type} parser: {e}")
    
    async def get_available_parsers(self) -> List[str]:
        """
        Get list of available and configured parsers.
        
        Returns:
            List of parser type names
        """
        available = []
        for parser_type, parser in self.parsers.items():
            try:
                if await parser.check_availability():
                    available.append(parser_type)
            except Exception as e:
                logger.warning(f"Error checking availability of {parser_type} parser: {e}")
        return available
    
    def get_parser(self, parser_type: str) -> Optional[BaseParser]:
        """
        Get parser by type.
        
        Args:
            parser_type: Type of parser ('telethon', 'rss', 'web')
            
        Returns:
            Parser instance or None
        """
        return self.parsers.get(parser_type)
    
    async def parse_channel(
        self,
        channel_username: str,
        source_type: Optional[str] = None,
        limit: Optional[int] = None,
        days: Optional[int] = None,
        fallback: bool = True
    ) -> Dict[str, Any]:
        """
        Parse channel using appropriate parser with fallback mechanism.
        
        Args:
            channel_username: Channel username or identifier
            source_type: Preferred source type (None = auto-select)
            limit: Maximum number of messages to fetch
            days: Number of days to look back
            fallback: Whether to try fallback parsers if preferred fails
            
        Returns:
            Dict with parsing results
        """
        # Determine which parsers to try
        parsers_to_try = []
        
        if source_type:
            # Use specified parser type
            if source_type in self.parsers:
                parsers_to_try.append(source_type)
            elif fallback:
                # Try all available parsers as fallback
                parsers_to_try.extend(config.get_parser_priority())
        else:
            # Try parsers in priority order
            parsers_to_try = config.get_parser_priority().copy()
        
        # Remove duplicates while preserving order
        seen = set()
        parsers_to_try = [p for p in parsers_to_try if p not in seen and not seen.add(p)]
        
        # Try each parser
        last_error = None
        for parser_type in parsers_to_try:
            parser = self.parsers.get(parser_type)
            if not parser:
                continue
            
            # Check availability
            try:
                if not await parser.check_availability():
                    logger.debug(f"Parser {parser_type} is not available")
                    continue
            except Exception as e:
                logger.warning(f"Error checking availability of {parser_type}: {e}")
                continue
            
            # Try to parse
            try:
                logger.info(f"Trying to parse {channel_username} with {parser_type} parser")
                result = await parser.parse_channel(channel_username, limit=limit, days=days)
                
                # If we got some results, return them
                if result['parsed'] > 0 or result['errors'] == 0:
                    logger.info(f"Successfully parsed {channel_username} with {parser_type} parser")
                    return result
                else:
                    logger.warning(f"Parser {parser_type} returned no results for {channel_username}")
                    last_error = f"Parser {parser_type} returned no results"
                    
            except Exception as e:
                logger.error(f"Error parsing with {parser_type} parser: {e}")
                last_error = str(e)
                continue
        
        # If all parsers failed, return error result
        logger.error(f"All parsers failed for {channel_username}. Last error: {last_error}")
        return {
            'parsed': 0,
            'skipped': 0,
            'errors': 1,
            'messages': [],
            'error': last_error or 'All parsers failed'
        }
    
    async def get_channel_info(
        self,
        channel_username: str,
        source_type: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Get channel information using appropriate parser.
        
        Args:
            channel_username: Channel username or identifier
            source_type: Preferred source type (None = auto-select)
            
        Returns:
            Dict with channel info or None
        """
        # Determine which parsers to try
        parsers_to_try = []
        
        if source_type:
            if source_type in self.parsers:
                parsers_to_try.append(source_type)
        else:
            parsers_to_try = config.get_parser_priority().copy()
        
        # Try each parser
        for parser_type in parsers_to_try:
            parser = self.parsers.get(parser_type)
            if not parser:
                continue
            
            try:
                if not await parser.check_availability():
                    continue
                
                info = await parser.get_channel_info(channel_username)
                if info:
                    return info
                    
            except Exception as e:
                logger.warning(f"Error getting channel info with {parser_type}: {e}")
                continue
        
        return None
    
    async def close_all(self):
        """Close all parser connections."""
        for parser_type, parser in self.parsers.items():
            try:
                if hasattr(parser, 'disconnect'):
                    await parser.disconnect()
                elif hasattr(parser, 'close'):
                    await parser.close()
            except Exception as e:
                logger.warning(f"Error closing {parser_type} parser: {e}")
