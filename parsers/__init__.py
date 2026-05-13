"""Parsers package for news aggregation from various sources.

NewsTgBot - Self-hosted IT news aggregator
Copyright (C) 2026 therudywolf
Licensed under AGPL-3.0
"""
from .base import BaseParser
from .parser_manager import ParserManager
from .telethon_parser import TelethonParser
from .rss_parser import RSSParser
from .web_parser import WebParser

__all__ = ['BaseParser', 'ParserManager', 'TelethonParser', 'RSSParser', 'WebParser']

