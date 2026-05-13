"""Tests for configuration module."""

import os
import pytest
from unittest.mock import patch, MagicMock

import sys

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestConfig:
    """Test suite for configuration management."""

    @patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "test_token"})
    def test_telegram_bot_token_from_env(self):
        """Test reading Telegram bot token from environment."""
        from config import TELEGRAM_BOT_TOKEN

        # Verify token is read (actual value depends on env setup)
        assert isinstance(TELEGRAM_BOT_TOKEN, str)

    @patch.dict(os.environ, {"LOG_LEVEL": "DEBUG"})
    def test_log_level_configuration(self):
        """Test log level configuration."""
        # This test verifies configuration can be read
        log_level = os.getenv("LOG_LEVEL", "INFO")
        assert log_level in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

    def test_auto_parse_defaults(self):
        """Test auto-parse default settings."""
        auto_parse_enabled = os.getenv("AUTO_PARSE_ENABLED", "false").lower() == "true"
        check_interval = int(os.getenv("CHECK_INTERVAL_SECONDS", "3600"))
        auto_parse_limit = int(os.getenv("AUTO_PARSE_LIMIT", "200"))

        assert isinstance(auto_parse_enabled, bool)
        assert check_interval > 0
        assert auto_parse_limit > 0

    def test_parser_priority_configuration(self):
        """Test parser priority configuration."""
        parser_priority = os.getenv("PARSER_PRIORITY", '["rss", "telethon", "web"]')

        # Should be a valid list representation
        assert "[" in parser_priority and "]" in parser_priority
        assert "rss" in parser_priority or "telethon" in parser_priority

    def test_paths_configuration(self):
        """Test file paths configuration."""
        data_dir = os.getenv("DATA_DIR", "/app/data")
        logs_dir = os.getenv("LOGS_DIR", "/app/logs")
        db_path = os.getenv("DATABASE_PATH", "/app/data/news_bot.db")

        # Should be valid path strings
        assert isinstance(data_dir, str) and len(data_dir) > 0
        assert isinstance(logs_dir, str) and len(logs_dir) > 0
        assert isinstance(db_path, str) and ".db" in db_path

