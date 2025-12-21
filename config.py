"""Configuration module for News Telegram Bot."""
import os
import logging
import sys
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Настройка логирования
def setup_logging():
    """Настроить логирование для приложения."""
    log_format = '[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s'
    date_format = '%Y-%m-%d %H:%M:%S'
    
    # Настройка root logger
    logging.basicConfig(
        level=logging.INFO,
        format=log_format,
        datefmt=date_format,
        handlers=[
            logging.StreamHandler(sys.stdout)  # Вывод в stdout для Docker
        ]
    )
    
    # Установка уровня логирования для внешних библиотек
    logging.getLogger('httpx').setLevel(logging.WARNING)
    logging.getLogger('telegram').setLevel(logging.WARNING)
    logging.getLogger('aiohttp').setLevel(logging.WARNING)

# Инициализация логирования при импорте модуля
setup_logging()

# Получить логгер для этого модуля
logger = logging.getLogger(__name__)

# Telegram Bot Configuration
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN environment variable is not set")

# LLM API Configuration
LLM_API_URL = os.getenv("LLM_API_URL")
if not LLM_API_URL:
    raise ValueError("LLM_API_URL environment variable is not set")

LLM_MODEL_NAME = os.getenv("LLM_MODEL_NAME")
if not LLM_MODEL_NAME:
    raise ValueError("LLM_MODEL_NAME environment variable is not set")

# Database configuration (может быть переопределено через переменную окружения)
DATABASE_PATH = os.getenv("DATABASE_PATH", "news_bot.db")

# Channels configuration file (может быть переопределено через переменную окружения)
CHANNELS_JSON_PATH = os.getenv("CHANNELS_JSON_PATH", "channels.json")

# Scheduler configuration (check interval in seconds)
CHECK_INTERVAL_SECONDS = 3600  # 1 hour

# Parser configuration

# Telethon parser configuration (MTProto Client API)
TELETHON_API_ID = os.getenv("TELETHON_API_ID")  # Get from https://my.telegram.org
TELETHON_API_HASH = os.getenv("TELETHON_API_HASH")  # Get from https://my.telegram.org
TELETHON_PHONE = os.getenv("TELETHON_PHONE")  # Phone number with country code (e.g., +1234567890)
TELETHON_SESSION_FILE = os.getenv("TELETHON_SESSION_FILE", "data/telethon_session.session")

# Web parser configuration
WEB_PARSER_HEADLESS = os.getenv("WEB_PARSER_HEADLESS", "true").lower() == "true"  # Run browser in headless mode
WEB_PARSER_TIMEOUT = int(os.getenv("WEB_PARSER_TIMEOUT", "30"))  # Timeout in seconds
WEB_PARSER_ENGINE = os.getenv("WEB_PARSER_ENGINE", "playwright")  # 'playwright' or 'selenium'

# RSS parser configuration
RSS_PARSER_TIMEOUT = int(os.getenv("RSS_PARSER_TIMEOUT", "10"))  # Timeout in seconds for fetching RSS feeds

# Parser priority (order matters - first tried first)
PARSER_PRIORITY_STR = os.getenv("PARSER_PRIORITY", '["telethon", "web", "rss"]')
try:
    import json
    PARSER_PRIORITY = json.loads(PARSER_PRIORITY_STR)
except (json.JSONDecodeError, ValueError):
    PARSER_PRIORITY = ["telethon", "web", "rss"]  # Default priority

