"""Pytest configuration and shared fixtures."""

import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def test_data_dir():
    """Create temporary test data directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def test_env_file(test_data_dir):
    """Create test .env file."""
    env_path = Path(test_data_dir) / ".env.test"
    env_content = """
TELEGRAM_BOT_TOKEN=test_token_123
TELETHON_API_ID=12345
TELETHON_API_HASH=your_telethon_api_hash
TELETHON_PHONE=+79990000000
LM_STUDIO_BASE_URL=http://localhost:1234
LM_STUDIO_API_TOKEN=test
DATABASE_PATH={}/test.db
DATA_DIR={}
LOGS_DIR={}
AUTO_PARSE_ENABLED=false
""".format(test_data_dir, test_data_dir, test_data_dir)

    env_path.write_text(env_content)
    return str(env_path)


@pytest.fixture
def mock_database(test_data_dir):
    """Create mock database for testing."""
    db_path = Path(test_data_dir) / "test.db"
    return str(db_path)


@pytest.fixture
def mock_logger(mocker):
    """Mock logger for testing."""
    return mocker.patch("logging.getLogger")


@pytest.fixture
def sample_rss_feed():
    """Sample RSS feed for testing."""
    return """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Feed</title>
    <link>https://example.com</link>
    <description>Test Description</description>
    <item>
      <title>Test Article</title>
      <link>https://example.com/article1</link>
      <description>Test article content</description>
      <pubDate>Mon, 12 May 2026 12:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""


@pytest.fixture
def sample_telegram_message():
    """Sample Telegram message for testing."""
    return {
        "message_id": 123,
        "date": 1715500800,
        "text": "Test message from channel",
        "forward_from_chat": {
            "id": -1001234567890,
            "title": "Test Channel",
            "type": "channel",
        },
    }

