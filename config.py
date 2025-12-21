"""Configuration module for News Telegram Bot."""
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

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

# Database configuration
DATABASE_PATH = "news_bot.db"

# Channels configuration file
CHANNELS_JSON_PATH = "channels.json"

# Scheduler configuration (check interval in seconds)
CHECK_INTERVAL_SECONDS = 3600  # 1 hour

