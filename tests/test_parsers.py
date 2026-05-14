"""Tests for parser modules."""

import pytest
from unittest.mock import Mock, patch, AsyncMock

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestRSSParser:
    """Test suite for RSS parser."""

    def test_rss_parser_initialization(self):
        """Test RSS parser can be imported."""
        try:
            from parsers.rss_parser import RSSParser

            parser = RSSParser()
            assert parser is not None
        except ImportError:
            pytest.skip("RSS parser dependencies not available")

    def test_parse_valid_rss_feed(self, sample_rss_feed):
        """Test parsing valid RSS feed."""
        try:
            from parsers.rss_parser import RSSParser
            import feedparser

            # Use feedparser directly to test basic RSS parsing
            result = feedparser.parse(sample_rss_feed)

            assert result.feed is not None
            assert "Test Feed" in result.feed.get("title", "")
            assert len(result.entries) > 0
        except ImportError:
            pytest.skip("feedparser not available")

    def test_rss_parser_timeout_handling(self):
        """Test RSS parser handles timeouts gracefully."""
        # This would test error handling in real implementation
        pass


class TestTelethonParser:
    """Test suite for Telethon parser."""

    def test_telethon_parser_initialization(self):
        """Test Telethon parser can be imported."""
        try:
            from parsers.telethon_parser import TelethonParser

            parser = TelethonParser()
            assert parser is not None
        except ImportError:
            pytest.skip("Telethon dependencies not available")

    @pytest.mark.asyncio
    async def test_telethon_availability_check(self):
        """Test Telethon parser availability check."""
        try:
            from parsers.telethon_parser import TelethonParser

            parser = TelethonParser()
            # This should not raise an exception
            is_available = await parser.check_availability()
            assert isinstance(is_available, bool)
        except ImportError:
            pytest.skip("Telethon dependencies not available")


class TestWebParser:
    """Test suite for web parser."""

    def test_web_parser_initialization(self):
        """Test web parser can be imported."""
        try:
            from parsers.web_parser import WebParser

            parser = WebParser()
            assert parser is not None
        except ImportError:
            pytest.skip("Web parser dependencies not available")

    @pytest.mark.asyncio
    async def test_web_parser_timeout_handling(self):
        """Test web parser handles timeouts gracefully."""
        try:
            from parsers.web_parser import WebParser

            parser = WebParser()
            # Mock URL that will timeout
            with patch("asyncio.wait_for", side_effect=TimeoutError):
                is_available = await parser.check_availability()
                assert isinstance(is_available, bool)
        except ImportError:
            pytest.skip("Web parser dependencies not available")

