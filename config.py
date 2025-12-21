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

