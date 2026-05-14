"""Configuration module for News Telegram Bot.

NewsTgBot - Self-hosted IT news aggregator
Copyright (C) 2026 therudywolf

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published
by the Free Software Foundation, either version 3 of the License.
See LICENSE file for details.
"""
import json
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _float_env(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return float(value)
    except ValueError:
        return default


def setup_logging():
    """Configure process logging."""
    log_format = "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format=log_format,
        datefmt=date_format,
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)
    logging.getLogger("telethon").setLevel(logging.WARNING)
    logging.getLogger("aiohttp").setLevel(logging.WARNING)


setup_logging()
logger = logging.getLogger(__name__)

DATA_DIR = Path(os.getenv("DATA_DIR", "data"))
LOGS_DIR = Path(os.getenv("LOGS_DIR", "logs"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# Telegram Bot API configuration. The admin panel can run without this token.
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()

# Telegram user-account parser configuration (MTProto Client API).
TELETHON_API_ID = os.getenv("TELETHON_API_ID", "").strip()
TELETHON_API_HASH = os.getenv("TELETHON_API_HASH", "").strip()
TELETHON_PHONE = os.getenv("TELETHON_PHONE", "").strip()
TELETHON_SESSION_FILE = os.getenv(
    "TELETHON_SESSION_FILE",
    str(DATA_DIR / "telethon_session.session"),
)

# LM Studio configuration. Native /api/v1 is preferred; OpenAI-compatible mode is
# available as a fallback for older setups and external compatible servers.
LM_STUDIO_BASE_URL = os.getenv(
    "LM_STUDIO_BASE_URL",
    os.getenv("LLM_API_URL", "http://localhost:1234"),
).strip()
LM_STUDIO_API_TOKEN = os.getenv(
    "LM_STUDIO_API_TOKEN",
    os.getenv("LLM_API_TOKEN", ""),
).strip()
LM_STUDIO_MODEL = os.getenv(
    "LM_STUDIO_MODEL",
    os.getenv("LLM_MODEL_NAME", ""),
).strip()
LM_STUDIO_API_MODE = os.getenv("LM_STUDIO_API_MODE", "native").strip().lower()
LLM_TEMPERATURE = _float_env("LLM_TEMPERATURE", 0.2)
LLM_MAX_OUTPUT_TOKENS = _int_env("LLM_MAX_OUTPUT_TOKENS", 2048)
LLM_CONTEXT_LENGTH = _int_env("LLM_CONTEXT_LENGTH", 8192)

# Backward-compatible names used by older modules.
LLM_API_URL = LM_STUDIO_BASE_URL
LLM_MODEL_NAME = LM_STUDIO_MODEL

DATABASE_PATH = os.getenv("DATABASE_PATH", str(DATA_DIR / "news_bot.db"))
CHANNELS_JSON_PATH = os.getenv("CHANNELS_JSON_PATH", str(DATA_DIR / "channels.json"))

CHECK_INTERVAL_SECONDS = _int_env("CHECK_INTERVAL_SECONDS", 3600)
AUTO_PARSE_ENABLED = _bool_env("AUTO_PARSE_ENABLED", False)
AUTO_PARSE_LIMIT = _int_env("AUTO_PARSE_LIMIT", 200)
AUTO_PARSE_DAYS = _int_env("AUTO_PARSE_DAYS", 7)

WEB_PARSER_HEADLESS = _bool_env("WEB_PARSER_HEADLESS", True)
WEB_PARSER_TIMEOUT = _int_env("WEB_PARSER_TIMEOUT", 30)
WEB_PARSER_ENGINE = os.getenv("WEB_PARSER_ENGINE", "playwright").strip().lower()

RSS_PARSER_TIMEOUT = _int_env("RSS_PARSER_TIMEOUT", 15)

PARSER_PRIORITY_STR = os.getenv("PARSER_PRIORITY", '["telethon", "rss", "web"]')
try:
    PARSER_PRIORITY = json.loads(PARSER_PRIORITY_STR)
    if not isinstance(PARSER_PRIORITY, list):
        raise ValueError("PARSER_PRIORITY must be a JSON list")
except (json.JSONDecodeError, ValueError):
    PARSER_PRIORITY = ["telethon", "rss", "web"]


def _db_setting(key: str, default=None):
    """Read a setting from the DB app_settings table, falling back to *default*."""
    try:
        import sqlite3

        db_path = DATABASE_PATH
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT value FROM app_settings WHERE key = ?", (key,))
        row = cur.fetchone()
        conn.close()
        if row:
            val = json.loads(row["value"])
            if val not in (None, ""):
                return val
    except Exception:
        pass
    return default


def get_bot_token() -> str:
    """Telegram bot token: DB override > env."""
    return str(_db_setting("telegram_bot_token") or TELEGRAM_BOT_TOKEN).strip()


def get_telethon_api_id() -> str:
    return str(_db_setting("telethon_api_id") or TELETHON_API_ID).strip()


def get_telethon_api_hash() -> str:
    return str(_db_setting("telethon_api_hash") or TELETHON_API_HASH).strip()


def get_telethon_phone() -> str:
    return str(_db_setting("telethon_phone") or TELETHON_PHONE).strip()


def get_auto_parse_enabled() -> bool:
    val = _db_setting("auto_parse_enabled")
    if val is not None:
        return bool(val)
    return AUTO_PARSE_ENABLED


def get_check_interval() -> int:
    return int(_db_setting("check_interval_seconds") or CHECK_INTERVAL_SECONDS)


def get_auto_parse_limit() -> int:
    return int(_db_setting("auto_parse_limit") or AUTO_PARSE_LIMIT)


def get_auto_parse_days() -> int:
    return int(_db_setting("auto_parse_days") or AUTO_PARSE_DAYS)
