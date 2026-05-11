"""Main bot file for Telegram News Aggregator."""
import json
import logging
import os
import re
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes, TypeHandler
import config
import database
import channel_reader
import deduplicator
import llm_client
import scheduler
from source_identity import stable_source_id

logger = logging.getLogger(__name__)


class NewsBot:
    """Main bot class."""
    
    def __init__(self):
        """Initialize the bot."""
        self.db = database.Database()
        self.channel_reader = channel_reader.ChannelReader(self.db)
        self.llm_client = llm_client.LLMClient()
        self.deduplicator = deduplicator.Deduplicator(self.llm_client)
        self.scheduler = scheduler.Scheduler()
        self.app = None
        self.default_sources = self._load_default_sources()
    
    def _load_default_sources(self) -> Dict:
        """Load default sources from JSON file."""
        default_sources_path = os.path.join(os.path.dirname(__file__), "default_sources.json")
        try:
            if os.path.exists(default_sources_path):
                with open(default_sources_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            else:
                logger.warning(f"Default sources file not found at {default_sources_path}")
                return {"categories": {}}
        except Exception as e:
            logger.error(f"Error loading default sources: {e}")
            return {"categories": {}}
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command."""
        welcome_message = """👋 Привет! Я бот для агрегации новостей.

📰 Я собираю новости из различных источников (RSS, Telegram каналы) и создаю краткие сводки.

🎯 Выберите действие ниже:"""
        
        keyboard = self._create_main_keyboard()
        await update.message.reply_text(
            welcome_message,
            reply_markup=keyboard
        )
    
    def _create_main_keyboard(self) -> ReplyKeyboardMarkup:
        """Create main reply keyboard."""
        keyboard = [
            ["➕ Добавить источники", "📰 Получить новости"],
            ["📋 Мои источники", "📊 Статистика"],
            ["⚙️ Настройки"]
        ]
        return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    def _create_channels_inline_keyboard(self, channels: List[Dict]) -> InlineKeyboardMarkup:
        """Create inline keyboard for channels list."""
        buttons = []
        for channel in channels:
            channel_id = channel.get('channel_id')
            title = channel.get('title', 'N/A')[:30]  # Limit title length
            buttons.append([
                InlineKeyboardButton(
                    f"📺 {title}",
                    callback_data=f"channel_info:{channel_id}"
                )
            ])
        
        # Add action buttons
        buttons.append([
            InlineKeyboardButton("🔄 Парсить все", callback_data="parse_all"),
            InlineKeyboardButton("📊 Статистика", callback_data="global_stats")
        ])
        
        return InlineKeyboardMarkup(buttons)
    
    def _create_channel_actions_keyboard(self, channel_id: int) -> InlineKeyboardMarkup:
        """Create inline keyboard for channel actions."""
        buttons = [
            [
                InlineKeyboardButton("🔄 Парсить", callback_data=f"parse_channel:{channel_id}"),
                InlineKeyboardButton("📊 Статистика", callback_data=f"channel_stats:{channel_id}")
            ],
            [
                InlineKeyboardButton("⚙️ Изменить источник", callback_data=f"change_source_menu:{channel_id}"),
                InlineKeyboardButton("❌ Удалить", callback_data=f"confirm_remove:{channel_id}")
            ],
            [
                InlineKeyboardButton("🔙 Назад", callback_data="list_channels")
            ]
        ]
        return InlineKeyboardMarkup(buttons)
    
    def _create_period_keyboard(self) -> InlineKeyboardMarkup:
        """Create inline keyboard for period selection."""
        buttons = [
            [
                InlineKeyboardButton("📅 1 день", callback_data="period:1d"),
                InlineKeyboardButton("📅 7 дней", callback_data="period:7d")
            ],
            [
                InlineKeyboardButton("📅 30 дней", callback_data="period:30d")
            ],
            [InlineKeyboardButton("🔙 Главное меню", callback_data="main_menu")]
        ]
        return InlineKeyboardMarkup(buttons)
    
    def _create_add_sources_keyboard(self) -> InlineKeyboardMarkup:
        """Create keyboard for adding sources menu."""
        buttons = []
        
        # Add category buttons
        categories = self.default_sources.get("categories", {})
        if categories:
            buttons.append([InlineKeyboardButton("📚 Предустановленные источники", callback_data="default_sources_menu")])
        
        buttons.append([InlineKeyboardButton("🔗 Добавить вручную", callback_data="add_manual_source")])
        buttons.append([InlineKeyboardButton("🔙 Главное меню", callback_data="main_menu")])
        
        return InlineKeyboardMarkup(buttons)
    
    def _create_categories_keyboard(self) -> InlineKeyboardMarkup:
        """Create keyboard for source categories."""
        buttons = []
        categories = self.default_sources.get("categories", {})
        
        for category_id, category_data in categories.items():
            category_name = category_data.get("name", category_id)
            buttons.append([
                InlineKeyboardButton(category_name, callback_data=f"category:{category_id}")
            ])
        
        buttons.append([InlineKeyboardButton("🔙 Назад", callback_data="default_sources_menu")])
        return InlineKeyboardMarkup(buttons)
    
    def _create_category_sources_keyboard(self, category_id: str) -> InlineKeyboardMarkup:
        """Create keyboard for sources in a category."""
        buttons = []
        categories = self.default_sources.get("categories", {})
        category_data = categories.get(category_id, {})
        sources = category_data.get("sources", [])
        
        existing_channel_ids = {ch.get('channel_id') for ch in self.db.get_all_channels()}
        
        for source in sources:
            title = source.get("title", "Unknown")
            username = source.get("username", "")
            source_type = source.get("source_type", "rss")
            
            identifier = source.get("source_config", {}).get("rss_url") if source_type == "rss" else username
            is_added = stable_source_id(identifier or username, source_type) in existing_channel_ids
            prefix = "✅ " if is_added else ""
            
            buttons.append([
                InlineKeyboardButton(
                    f"{prefix}{title}",
                    callback_data=f"add_default_source:{category_id}:{username}"
                )
            ])
        
        buttons.append([InlineKeyboardButton("🔙 К категориям", callback_data="default_sources_menu")])
        return InlineKeyboardMarkup(buttons)
    
    def _create_source_type_keyboard(self, channel_id: int, is_change: bool = False) -> InlineKeyboardMarkup:
        """Create inline keyboard for source type selection."""
        prefix = "change_source" if is_change else "add_channel_source"
        buttons = [
            [
                InlineKeyboardButton("📱 Telethon", callback_data=f"{prefix}:{channel_id}:telethon"),
                InlineKeyboardButton("🌐 Web", callback_data=f"{prefix}:{channel_id}:web")
            ],
            [
                InlineKeyboardButton("📡 RSS", callback_data=f"{prefix}:{channel_id}:rss"),
                InlineKeyboardButton("🤖 Bot API", callback_data=f"{prefix}:{channel_id}:telegram_bot")
            ]
        ]
        
        if is_change:
            buttons.append([
                InlineKeyboardButton("🔙 К каналу", callback_data=f"channel_info:{channel_id}")
            ])
        else:
            buttons.append([
                InlineKeyboardButton("❌ Отмена", callback_data="cancel_add_channel")
            ])
        
        return InlineKeyboardMarkup(buttons)
    
    def _create_tags_keyboard(self, tags: List[Dict], page: int = 0, per_page: int = 10) -> InlineKeyboardMarkup:
        """Create inline keyboard for tags."""
        buttons = []
        start_idx = page * per_page
        end_idx = start_idx + per_page
        
        for tag in tags[start_idx:end_idx]:
            tag_id = tag.get('id')
            tag_name = tag.get('name', 'N/A')
            usage = tag.get('usage_count', 0)
            buttons.append([
                InlineKeyboardButton(
                    f"#{tag_name} ({usage})",
                    callback_data=f"tag:{tag_id}"
                )
            ])
        
        # Pagination buttons
        nav_buttons = []
        if page > 0:
            nav_buttons.append(InlineKeyboardButton("◀️ Назад", callback_data=f"tags_page:{page-1}"))
        if end_idx < len(tags):
            nav_buttons.append(InlineKeyboardButton("Вперед ▶️", callback_data=f"tags_page:{page+1}"))
        if nav_buttons:
            buttons.append(nav_buttons)
        
        buttons.append([InlineKeyboardButton("🔙 Главное меню", callback_data="main_menu")])
        return InlineKeyboardMarkup(buttons)
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command."""
        help_text = """
📖 Справка по командам:

/add_channel <ссылка>
Добавляет канал для отслеживания.
Пример: /add_channel @channel_name или /add_channel https://t.me/channel_name
⚠️ Бот должен быть добавлен в канал как администратор или участник.

/remove_channel <ссылка или ID>
Удаляет канал из списка отслеживаемых.
Пример: /remove_channel @channel_name

/list_channels
Показывает все отслеживаемые каналы.

/get_news <период>
Получает агрегированные новости за указанный период.
Примеры:
• /get_news 1d - за последние 24 часа
• /get_news 7d - за последние 7 дней
• /get_news 30d - за последние 30 дней
• /get_news 2024-01-01:2024-01-07 - с 1 по 7 января 2024

Бот автоматически удаляет дубликаты и создает краткую сводку новостей.
"""
        await update.message.reply_text(help_text)
    
    async def add_channel_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /add_channel command."""
        if not context.args:
            await update.message.reply_text(
                "Использование: /add_channel <ссылка на канал>\n"
                "Пример: /add_channel @channel_name"
            )
            return
        
        channel_input = " ".join(context.args)
        
        # Try to extract channel username or ID from input
        channel_id = None
        username = None
        
        # Try to get channel info by username if it's a link
        if channel_input.startswith("https://t.me/"):
            username = channel_input.replace("https://t.me/", "").lstrip("/")
        elif channel_input.startswith("@"):
            username = channel_input.lstrip("@")
        else:
            # Try as username without @
            username = channel_input
        
        # Try to get channel info - first try bot API, then try parsers
        channel_id = None
        title = username
        
        try:
            # Try bot API first (works if bot is admin)
            chat = await context.bot.get_chat(f"@{username}" if username else channel_input)
            channel_id = chat.id
            title = chat.title or username
        except Exception as e:
            # If bot API fails, try to get info via parsers
            logger.info(f"Bot API failed for {username}, trying parsers: {e}")
            try:
                channel_info = await self.channel_reader.parser_manager.get_channel_info(username)
                if channel_info:
                    channel_id = channel_info.get('channel_id')
                    title = channel_info.get('title', username)
                    # If parser returned channel_id, use it, otherwise generate pseudo ID
                    if not channel_id:
                        channel_id = stable_source_id(username, "telegram")
            except Exception as parser_error:
                logger.warning(f"Parsers also failed: {parser_error}")
        
        if not channel_id:
            await update.message.reply_text(
                f"Ошибка при добавлении канала: не удалось получить информацию о канале.\n"
                "Попробуйте:\n"
                "1. Убедиться, что канал существует\n"
                "2. Для Bot API: добавить бота в канал как администратора\n"
                "3. Для других источников: убедиться, что парсеры настроены правильно"
            )
            return
        
        # Show source selection keyboard
        message = f"Канал найден: {title} (@{username})\n\nВыберите способ парсинга:"
        keyboard = self._create_source_type_keyboard(channel_id, is_change=False)
        
        # Store pending channel info temporarily
        # We'll use callback to complete the addition
        await update.message.reply_text(message, reply_markup=keyboard)
    
    async def remove_channel_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /remove_channel command."""
        if not context.args:
            await update.message.reply_text(
                "Использование: /remove_channel <ссылка или ID канала>"
            )
            return
        
        channel_input = " ".join(context.args)
        
        # Try to extract channel ID
        channel_id = None
        
        # Try as username
        if channel_input.startswith("https://t.me/"):
            username = channel_input.replace("https://t.me/", "").lstrip("/")
        elif channel_input.startswith("@"):
            username = channel_input.lstrip("@")
        else:
            username = channel_input
        
        # Try to get channel info
        try:
            chat = await context.bot.get_chat(f"@{username}" if username else channel_input)
            channel_id = chat.id
        except Exception:
            try:
                channel_id = int(channel_input)
            except (ValueError, TypeError):
                pass
        
        if not channel_id:
            await update.message.reply_text("Не удалось определить канал.")
            return
        
        # Remove from database
        success = self.db.remove_channel(channel_id)
        
        # Remove from channels.json
        self._remove_channel_from_json(channel_id)
        
        if success:
            logger.info(f"Channel removed: ID {channel_id}")
            await update.message.reply_text("✅ Канал успешно удален!")
        else:
            logger.warning(f"Channel not found for removal: ID {channel_id}")
            await update.message.reply_text("⚠️ Канал не найден в списке.")
    
    async def list_channels_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /list_channels command."""
        await self._show_channels_list(update)
    
    async def _show_channels_list(self, update: Update):
        """Show channels list with inline keyboard."""
        channels = self.db.get_all_channels()
        
        if not channels:
            await update.message.reply_text("Список каналов пуст.")
            return
        
        message = "📋 Отслеживаемые каналы:\n\n"
        for idx, channel in enumerate(channels, 1):
            username = channel.get('username', 'N/A')
            title = channel.get('title', 'N/A')
            source_type = channel.get('source_type', 'telegram_bot')
            source_emoji = {'telethon': '📱', 'web': '🌐', 'rss': '📡', 'telegram_bot': '🤖'}.get(source_type, '📺')
            message += f"{idx}. {source_emoji} {title} (@{username})\n"
        
        keyboard = self._create_channels_inline_keyboard(channels)
        await update.message.reply_text(message, reply_markup=keyboard)
    
    async def get_news_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /get_news command."""
        if not context.args:
            await update.message.reply_text(
                "Использование: /get_news <период>\n"
                "Примеры: /get_news 1d, /get_news 7d, /get_news 2024-01-01:2024-01-07"
            )
            return
        
        period_input = " ".join(context.args)
        
        # Parse period
        start_date, end_date = self._parse_period(period_input)
        if not start_date or not end_date:
            await update.message.reply_text(
                "Неверный формат периода.\n"
                "Используйте: 1d, 7d, 30d или 2024-01-01:2024-01-07"
            )
            return
        
        # Show processing message
        processing_msg = await update.message.reply_text("⏳ Обрабатываю новости...")
        
        try:
            # Get news from database
            news_items = self.db.get_news_by_period(
                start_date.isoformat(),
                end_date.isoformat()
            )
            
            if not news_items:
                await processing_msg.edit_text(
                    f"Новостей за период с {start_date.date()} по {end_date.date()} не найдено."
                )
                return
            
            # Deduplicate using LLM
            logger.info(f"Processing {len(news_items)} news items for period {start_date.date()} - {end_date.date()}")
            await processing_msg.edit_text(f"🔍 Найдено {len(news_items)} новостей. Удаляю дубликаты...")
            unique_news = await self.deduplicator.deduplicate(news_items)
            
            if not unique_news:
                logger.warning("No unique news after deduplication")
                await processing_msg.edit_text("После удаления дубликатов новостей не осталось.")
                return
            
            logger.info(f"After deduplication: {len(unique_news)} unique news items")
            # Aggregate using LLM
            await processing_msg.edit_text(
                f"📝 Уникальных новостей: {len(unique_news)}. Создаю сводку..."
            )
            period_desc = f"{start_date.date()} - {end_date.date()}"
            summary = await self.llm_client.aggregate_news(unique_news, period_desc)
            
            # Save session
            self.db.save_session(
                update.effective_user.id,
                start_date.isoformat(),
                end_date.isoformat(),
                summary
            )
            
            # Send result (split if too long)
            if len(summary) > 4096:
                # Telegram message limit is 4096 characters
                chunks = [summary[i:i+4090] for i in range(0, len(summary), 4090)]
                for i, chunk in enumerate(chunks):
                    if i == 0:
                        await processing_msg.edit_text(chunk)
                    else:
                        await update.message.reply_text(chunk)
            else:
                await processing_msg.edit_text(summary)
                
        except Exception as e:
            logger.error(f"Error in get_news_command: {e}", exc_info=True)
            await processing_msg.edit_text(f"❌ Ошибка при обработке новостей: {e}")
    
    async def handle_channel_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle messages from channels (both message and channel_post)."""
        # Handle channel_post (messages from channels) or message (for supergroups)
        message = update.channel_post or update.message
        
        if not message:
            return
        
        # Process channel message
        await self.channel_reader.process_channel_message(message)
    
    def _parse_period(self, period_input: str):
        """Parse period string into start and end dates."""
        period_input = period_input.strip().lower()
        
        # Try relative period (1d, 7d, 30d)
        match = re.match(r'^(\d+)d$', period_input)
        if match:
            days = int(match.group(1))
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days)
            return start_date, end_date
        
        # Try date range (2024-01-01:2024-01-07)
        match = re.match(r'^(\d{4}-\d{2}-\d{2}):(\d{4}-\d{2}-\d{2})$', period_input)
        if match:
            try:
                start_date = datetime.fromisoformat(match.group(1) + "T00:00:00")
                end_date = datetime.fromisoformat(match.group(2) + "T23:59:59")
                return start_date, end_date
            except ValueError:
                return None, None
        
        return None, None
    
    def _add_channel_to_json(self, channel_id: int, username: str, title: str):
        """Add channel to channels.json."""
        try:
            with open(config.CHANNELS_JSON_PATH, 'r', encoding='utf-8') as f:
                channels = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            channels = []
        
        # Check if already exists
        for ch in channels:
            if ch.get('channel_id') == channel_id:
                return
        
        channels.append({
            'channel_id': channel_id,
            'username': username,
            'title': title,
            'added_date': datetime.now().isoformat()
        })
        
        with open(config.CHANNELS_JSON_PATH, 'w', encoding='utf-8') as f:
            json.dump(channels, f, ensure_ascii=False, indent=2)
    
    def _remove_channel_from_json(self, channel_id: int):
        """Remove channel from channels.json."""
        try:
            with open(config.CHANNELS_JSON_PATH, 'r', encoding='utf-8') as f:
                channels = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return
        
        channels = [ch for ch in channels if ch.get('channel_id') != channel_id]
        
        with open(config.CHANNELS_JSON_PATH, 'w', encoding='utf-8') as f:
            json.dump(channels, f, ensure_ascii=False, indent=2)
    
    # Button handlers
    async def button_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle inline button callbacks."""
        query = update.callback_query
        await query.answer()
        
        data = query.data
        
        # Store context.bot for handlers
        self._current_context_bot = context.bot
        
        if data == "main_menu":
            await self._show_main_menu_inline(query)
        elif data == "list_channels":
            await self._show_channels_list_callback(query)
        elif data.startswith("channel_info:"):
            channel_id = int(data.split(":")[1])
            await self._show_channel_info(query, channel_id)
        elif data.startswith("parse_channel:"):
            channel_id = int(data.split(":")[1])
            await self._handle_parse_channel(query, channel_id, context)
        elif data == "parse_all":
            await self._handle_parse_all(query, context)
        elif data.startswith("channel_stats:"):
            channel_id = int(data.split(":")[1])
            await self._show_channel_stats(query, channel_id)
        elif data == "global_stats":
            await self._show_global_stats(query)
        elif data.startswith("period:"):
            period = data.split(":")[1]
            await self._handle_get_news_period(query, period)
        elif data.startswith("tag:"):
            tag_id = int(data.split(":")[1])
            await self._handle_tag_news(query, tag_id)
        elif data.startswith("tags_page:"):
            page = int(data.split(":")[1])
            await self._show_tags_list(query, page)
        elif data.startswith("confirm_remove:"):
            channel_id = int(data.split(":")[1])
            await self._confirm_remove_channel(query, channel_id)
        elif data.startswith("remove_channel:"):
            channel_id = int(data.split(":")[1])
            await self._handle_remove_channel(query, channel_id)
        elif data.startswith("add_channel_source:"):
            parts = data.split(":")
            channel_id = int(parts[1])
            source_type = parts[2]
            await self._handle_add_channel_with_source(query, channel_id, source_type)
        elif data.startswith("change_source:"):
            parts = data.split(":")
            channel_id = int(parts[1])
            source_type = parts[2]
            await self._handle_change_source(query, channel_id, source_type)
        elif data == "cancel_add_channel":
            await query.edit_message_text("Добавление канала отменено.")
        elif data == "parsers_status":
            await self._show_parsers_status(query)
        elif data.startswith("check_parser:"):
            parser_type = data.split(":")[1]
            await self._check_parser_status(query, parser_type)
        elif data.startswith("change_source_menu:"):
            channel_id = int(data.split(":")[1])
            await self._show_change_source_menu(query, channel_id)
        elif data == "default_sources_menu":
            await self._show_categories_menu(query)
        elif data.startswith("category:"):
            category_id = data.split(":")[1]
            await self._show_category_sources(query, category_id)
        elif data.startswith("add_default_source:"):
            parts = data.split(":", 2)  # Split only first 2 colons to handle URLs
            category_id = parts[1] if len(parts) > 1 else ""
            username = parts[2] if len(parts) > 2 else ""
            await self._handle_add_default_source(query, category_id, username)
        elif data == "add_manual_source":
            await self._handle_add_manual_source(query)
        elif data == "show_news_period":
            message = "📰 Получить новости\n\nВыберите период:"
            keyboard = self._create_period_keyboard()
            await query.edit_message_text(message, reply_markup=keyboard)
        else:
            logger.warning(f"Unhandled callback data: {data}")
    
    async def _show_channels_list_callback(self, query):
        """Show channels list from callback."""
        channels = self.db.get_all_channels()
        if not channels:
            await query.edit_message_text("Список каналов пуст.")
            return
        
        message = "📋 Отслеживаемые каналы:\n\n"
        for idx, channel in enumerate(channels, 1):
            username = channel.get('username', 'N/A')
            title = channel.get('title', 'N/A')
            source_type = channel.get('source_type', 'telegram_bot')
            source_emoji = {'telethon': '📱', 'web': '🌐', 'rss': '📡', 'telegram_bot': '🤖'}.get(source_type, '📺')
            message += f"{idx}. {source_emoji} {title} (@{username})\n"
        
        keyboard = self._create_channels_inline_keyboard(channels)
        await query.edit_message_text(message, reply_markup=keyboard)
    
    async def _show_channel_info(self, query, channel_id: int):
        """Show channel info with actions."""
        channel = self.db.get_channel_by_id(channel_id)
        if not channel:
            await query.answer("Канал не найден", show_alert=True)
            return
        
        message = f"📺 {channel.get('title', 'N/A')}\n"
        message += f"@{channel.get('username', 'N/A')}\n"
        message += f"ID: {channel_id}\n\n"
        
        # Show source type and status
        source_type = channel.get('source_type', 'telegram_bot')
        source_emoji = {'telethon': '📱', 'web': '🌐', 'rss': '📡', 'telegram_bot': '🤖'}.get(source_type, '📺')
        source_name = {'telethon': 'Telethon', 'web': 'Web Scraping', 'rss': 'RSS', 'telegram_bot': 'Bot API'}.get(source_type, source_type)
        
        # Check parser availability
        parser = self.channel_reader.parser_manager.get_parser(source_type)
        if parser and source_type != 'telegram_bot':
            try:
                is_available = await parser.check_availability()
                status_text = "активен" if is_available else "недоступен"
            except:
                status_text = "недоступен"
        else:
            status_text = "активен"
        
        message += f"Источник: {source_emoji} {source_name} ({status_text})\n\n"
        
        stats = self.db.get_channel_stats(channel_id)
        message += f"📊 Статистика:\n"
        message += f"Всего новостей: {stats['total']}\n"
        message += f"За день: {stats['day_count']}\n"
        message += f"За неделю: {stats['week_count']}\n"
        message += f"За месяц: {stats['month_count']}\n"
        if stats['latest_date']:
            latest = datetime.fromisoformat(stats['latest_date'])
            message += f"Последняя новость: {latest.strftime('%Y-%m-%d %H:%M')}\n"
        
        keyboard = self._create_channel_actions_keyboard(channel_id)
        await query.edit_message_text(message, reply_markup=keyboard)
    
    async def _handle_parse_channel(self, query, channel_id: int, context: ContextTypes.DEFAULT_TYPE = None):
        """Handle parse channel request."""
        await query.edit_message_text("⏳ Парсинг канала...")
        
        try:
            # Get channel info to determine username
            channel_info = self.db.get_channel_by_id(channel_id)
            if not channel_info:
                await query.edit_message_text("❌ Канал не найден")
                return
            
            channel_username = channel_info.get('username')
            
            # Get bot from context (for telegram_bot source type)
            bot = getattr(self, '_current_context_bot', None) or (context.bot if context else None) or (self.app.bot if self.app else None)
            
            # Parse channel using channel_reader (which handles source_type internally)
            stats = await self.channel_reader.force_parse_channel(
                bot=bot,
                channel_id=channel_id,
                channel_username=channel_username,
                limit=1000,
                days=30
            )
            
            message = f"✅ Парсинг завершен!\n\n"
            message += f"Распарсено: {stats['parsed']}\n"
            message += f"Пропущено: {stats['skipped']}\n"
            if stats['errors'] > 0:
                message += f"Ошибок: {stats['errors']}\n"
            
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 К каналу", callback_data=f"channel_info:{channel_id}")
            ]])
            await query.edit_message_text(message, reply_markup=keyboard)
        except Exception as e:
            logger.error(f"Error parsing channel {channel_id}: {e}", exc_info=True)
            await query.edit_message_text(f"❌ Ошибка при парсинге: {e}")
    
    async def _handle_parse_all(self, query, context: ContextTypes.DEFAULT_TYPE = None):
        """Handle parse all channels request."""
        channels = self.db.get_all_channels()
        if not channels:
            await query.answer("Нет каналов для парсинга", show_alert=True)
            return
        
        await query.edit_message_text(f"⏳ Парсинг {len(channels)} каналов...")
        
        # Get bot from context or app
        bot = getattr(self, '_current_context_bot', None) or (context.bot if context else None) or self.app.bot
        if not bot:
            await query.edit_message_text("❌ Ошибка: не удалось получить bot instance")
            return
        
        total_parsed = 0
        for channel in channels:
            try:
                channel_id = channel.get('channel_id')
                channel_username = channel.get('username')
                stats = await self.channel_reader.force_parse_channel(
                    bot=bot,
                    channel_id=channel_id,
                    channel_username=channel_username,
                    limit=500,
                    days=7
                )
                total_parsed += stats['parsed']
            except Exception as e:
                logger.error(f"Error parsing channel {channel_id}: {e}")
                continue
        
        message = f"✅ Парсинг всех каналов завершен!\n\n"
        message += f"Всего распарсено: {total_parsed} новостей"
        
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("🔙 К каналам", callback_data="list_channels")
        ]])
        await query.edit_message_text(message, reply_markup=keyboard)
    
    async def _show_channel_stats(self, query, channel_id: int):
        """Show channel statistics."""
        stats = self.db.get_channel_stats(channel_id)
        channel = self.db.get_channel_by_id(channel_id)
        
        message = f"📊 Статистика канала {channel.get('title', 'N/A') if channel else channel_id}\n\n"
        message += f"Всего новостей: {stats['total']}\n"
        message += f"За последний день: {stats['day_count']}\n"
        message += f"За последнюю неделю: {stats['week_count']}\n"
        message += f"За последний месяц: {stats['month_count']}\n"
        if stats['latest_date']:
            latest = datetime.fromisoformat(stats['latest_date'])
            message += f"\nПоследняя новость: {latest.strftime('%Y-%m-%d %H:%M')}"
        
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("🔙 К каналу", callback_data=f"channel_info:{channel_id}")
        ]])
        await query.edit_message_text(message, reply_markup=keyboard)
    
    async def _show_global_stats(self, query):
        """Show global statistics."""
        stats = self.db.get_global_stats()
        
        message = "📊 Общая статистика\n\n"
        message += f"Каналов: {stats['channels_count']}\n"
        message += f"Новостей: {stats['news_count']}\n"
        message += f"Тегов: {stats['tags_count']}\n"
        if stats['latest_date']:
            latest = datetime.fromisoformat(stats['latest_date'])
            message += f"\nПоследняя новость: {latest.strftime('%Y-%m-%d %H:%M')}"
        
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("🔙 Главное меню", callback_data="main_menu")
        ]])
        await query.edit_message_text(message, reply_markup=keyboard)
    
    async def _handle_get_news_period(self, query, period: str):
        """Handle get news by period from button."""
        start_date, end_date = self._parse_period(period)
        if not start_date or not end_date:
            await query.answer("Неверный период", show_alert=True)
            return
        
        await query.edit_message_text("⏳ Обрабатываю новости...")
        
        try:
            news_items = self.db.get_news_by_period(
                start_date.isoformat(),
                end_date.isoformat()
            )
            
            if not news_items:
                await query.edit_message_text(f"Новостей за период не найдено.")
                return
            
            await query.edit_message_text(f"🔍 Найдено {len(news_items)} новостей. Удаляю дубликаты...")
            unique_news = await self.deduplicator.deduplicate(news_items)
            
            if not unique_news:
                await query.edit_message_text("После удаления дубликатов новостей не осталось.")
                return
            
            await query.edit_message_text(f"📝 Уникальных новостей: {len(unique_news)}. Создаю сводку...")
            period_desc = f"{start_date.date()} - {end_date.date()}"
            summary = await self.llm_client.aggregate_news(unique_news, period_desc)
            
            if len(summary) > 4096:
                chunks = [summary[i:i+4090] for i in range(0, len(summary), 4090)]
                await query.edit_message_text(chunks[0])
                for chunk in chunks[1:]:
                    await query.message.reply_text(chunk)
            else:
                await query.edit_message_text(summary)
        except Exception as e:
            logger.error(f"Error in _handle_get_news_period: {e}", exc_info=True)
            await query.edit_message_text(f"❌ Ошибка: {e}")
    
    async def _handle_tag_news(self, query, tag_id: int):
        """Handle get news by tag."""
        news_items = self.db.get_news_by_tag(tag_id, limit=50)
        
        if not news_items:
            await query.answer("Новостей с этим тегом не найдено", show_alert=True)
            return
        
        await query.edit_message_text(f"📰 Найдено {len(news_items)} новостей. Обрабатываю...")
        
        # Deduplicate and aggregate
        unique_news = await self.deduplicator.deduplicate(news_items)
        if not unique_news:
            await query.edit_message_text("После удаления дубликатов новостей не осталось.")
            return
        
        summary = await self.llm_client.aggregate_news(unique_news, "по тегу")
        await query.edit_message_text(summary)
    
    async def _show_tags_list(self, query, page: int = 0):
        """Show tags list."""
        tags = self.db.get_all_tags(limit=100)
        
        if not tags:
            await query.edit_message_text("Тегов пока нет.")
            return
        
        message = f"🏷️ Теги (страница {page + 1}):\n\n"
        keyboard = self._create_tags_keyboard(tags, page)
        await query.edit_message_text(message, reply_markup=keyboard)
    
    # Text message handlers for reply keyboard
    async def handle_text_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle text messages (reply keyboard buttons)."""
        text = update.message.text
        
        if text == "➕ Добавить источники":
            await self._show_add_sources_menu(update)
        elif text == "📰 Получить новости":
            await self._show_news_period_menu(update)
        elif text == "📋 Мои источники":
            await self._show_channels_list(update)
        elif text == "📊 Статистика":
            await self._show_global_stats_text(update)
        elif text == "⚙️ Настройки":
            await self._show_settings_menu(update)
        else:
            # Only try to add channel if text looks like a channel identifier
            # Check if it's a valid channel format (not a button label)
            channel_input = text.strip()
            if (channel_input.startswith("@") or 
                channel_input.startswith("https://t.me/") or 
                channel_input.startswith("http://") or
                channel_input.startswith("https://")):
                await self._try_add_channel(update, text)
            else:
                # Probably not a channel - show help
                await update.message.reply_text(
                    "Введите username канала (например: @channel_name) или RSS ссылку.\n\n"
                    "Или используйте кнопки меню для навигации."
                )
    
    async def _show_tags_list_text(self, update: Update):
        """Show tags list from text command."""
        tags = self.db.get_all_tags(limit=100)
        
        if not tags:
            await update.message.reply_text("Тегов пока нет.")
            return
        
        message = "🏷️ Популярные теги:\n\n"
        for tag in tags[:20]:  # Show top 20
            name = tag.get('name', 'N/A')
            usage = tag.get('usage_count', 0)
            message += f"#{name} ({usage})\n"
        
        keyboard = self._create_tags_keyboard(tags, 0)
        await update.message.reply_text(message, reply_markup=keyboard)
    
    async def _show_global_stats_text(self, update: Update):
        """Show global stats from text command."""
        stats = self.db.get_global_stats()
        
        message = "📊 Общая статистика\n\n"
        message += f"Каналов: {stats['channels_count']}\n"
        message += f"Новостей: {stats['news_count']}\n"
        message += f"Тегов: {stats['tags_count']}\n"
        if stats['latest_date']:
            latest = datetime.fromisoformat(stats['latest_date'])
            message += f"\nПоследняя новость: {latest.strftime('%Y-%m-%d %H:%M')}"
        
        await update.message.reply_text(message)
    
    async def _try_add_channel(self, update: Update, text: str):
        """Try to add channel from text input."""
        # Skip if text looks like a button label (contains emoji and is not a valid channel format)
        channel_input = text.strip()
        
        # Don't try to parse button labels or non-channel text
        # Valid channel formats: @channel, https://t.me/channel, or plain channel name without spaces/emojis
        if not (channel_input.startswith("@") or 
                channel_input.startswith("https://t.me/") or 
                channel_input.startswith("http://") or
                channel_input.startswith("https://") or
                (len(channel_input) > 0 and " " not in channel_input and not any(ord(c) > 127 for c in channel_input if c not in "._-"))):
            # Probably not a channel - ignore silently or show help
            await update.message.reply_text(
                "Введите username канала (например: @channel_name) или RSS ссылку.\n\n"
                "Или используйте кнопки меню для навигации."
            )
            return
        
        # Try to extract channel username or ID
        username = None
        if channel_input.startswith("https://t.me/"):
            username = channel_input.replace("https://t.me/", "").lstrip("/")
        elif channel_input.startswith("http://") or channel_input.startswith("https://"):
            # RSS URL or web URL - handle as RSS source
            channel_id = stable_source_id(channel_input, "rss")
            title = channel_input.split("/")[-1] or "RSS Feed"
            success = self.db.add_channel(channel_id, channel_input, title, source_type='rss')
            if success:
                self.db.update_channel_source_type(channel_id, 'rss', {'rss_url': channel_input})
                await update.message.reply_text(f"✅ RSS источник добавлен: {title}")
            else:
                await update.message.reply_text("⚠️ Источник уже был добавлен ранее.")
            return
        elif channel_input.startswith("@"):
            username = channel_input.lstrip("@")
        else:
            username = channel_input
        
        # Try to get channel info - first try bot API, then try parsers
        channel_id = None
        title = username
        
        try:
            # Try bot API first (works if bot is admin)
            chat = await update.message.bot.get_chat(f"@{username}" if username else channel_input)
            channel_id = chat.id
            title = chat.title or username
        except Exception as e:
            # If bot API fails, try to get info via parsers
            logger.info(f"Bot API failed for {username}, trying parsers: {e}")
            try:
                channel_info = await self.channel_reader.parser_manager.get_channel_info(username)
                if channel_info:
                    channel_id = channel_info.get('channel_id')
                    title = channel_info.get('title', username)
                    # If parser returned channel_id, use it, otherwise generate pseudo ID
                    if not channel_id:
                        channel_id = stable_source_id(username, "telegram")
            except Exception as parser_error:
                logger.warning(f"Parsers also failed: {parser_error}")
                await update.message.reply_text(
                    f"Не удалось найти канал '{channel_input}'.\n\n"
                    "Проверьте:\n"
                    "• Правильность написания username\n"
                    "• Что канал существует и публичный\n"
                    "• Или используйте полную ссылку: https://t.me/channel_name"
                )
                return
        
        if not channel_id:
            await update.message.reply_text(
                f"Ошибка: не удалось получить информацию о канале.\n"
                "Попробуйте убедиться, что канал существует и доступен."
            )
            return
        
        # Show source selection keyboard
        message = f"Канал найден: {title} (@{username})\n\nВыберите способ парсинга:"
        keyboard = self._create_source_type_keyboard(channel_id, is_change=False)
        await update.message.reply_text(message, reply_markup=keyboard)
    
    async def _handle_add_channel_with_source(self, query, channel_id: int, source_type: str):
        """Handle adding channel with selected source type."""
        try:
            # Extract username and title from the previous message text
            message_text = query.message.text or ""
            username = None
            title = None
            
            # Try to extract from message text: "Канал найден: {title} (@{username})"
            import re
            match = re.search(r'Канал найден:\s*(.+?)\s*\(@(.+?)\)', message_text)
            if match:
                title = match.group(1).strip()
                username = match.group(2).strip()
            
            # If not found in message, try bot API
            if not username or not title:
                try:
                    bot = getattr(self, '_current_context_bot', None) or (self.app.bot if self.app else None)
                    if bot:
                        chat = await bot.get_chat(channel_id)
                        username = chat.username or str(channel_id)
                        title = chat.title or username
                except Exception as bot_error:
                    logger.warning(f"Bot API failed for channel {channel_id}: {bot_error}")
            
            # Fallback
            if not username:
                username = str(channel_id)
            if not title:
                title = f"Channel {channel_id}"
            
            # Add to database
            success = self.db.add_channel(channel_id, username, title, source_type=source_type)
            
            # Also add to channels.json
            self._add_channel_to_json(channel_id, username, title)
            
            if success:
                logger.info(f"Channel added: {title} (@{username}, ID: {channel_id}, source: {source_type})")
                source_emoji = {'telethon': '📱', 'web': '🌐', 'rss': '📡', 'telegram_bot': '🤖'}.get(source_type, '📺')
                await query.edit_message_text(
                    f"✅ Канал {title} (@{username}) успешно добавлен!\n"
                    f"Источник: {source_emoji} {source_type}"
                )
            else:
                await query.edit_message_text("⚠️ Канал уже был добавлен ранее.")
        except Exception as e:
            logger.error(f"Error adding channel with source: {e}", exc_info=True)
            await query.edit_message_text(f"❌ Ошибка при добавлении канала: {e}")
    
    async def _handle_change_source(self, query, channel_id: int, source_type: str):
        """Handle changing source type for a channel."""
        try:
            success = self.db.update_channel_source_type(channel_id, source_type)
            if success:
                source_emoji = {'telethon': '📱', 'web': '🌐', 'rss': '📡', 'telegram_bot': '🤖'}.get(source_type, '📺')
                await query.edit_message_text(f"✅ Источник изменен на: {source_emoji} {source_type}")
                # Refresh channel info
                await self._show_channel_info(query, channel_id)
            else:
                await query.edit_message_text("❌ Ошибка при изменении источника.")
        except Exception as e:
            logger.error(f"Error changing source: {e}", exc_info=True)
            await query.edit_message_text(f"❌ Ошибка: {e}")
    
    async def _show_parsers_status(self, query):
        """Show status of all parsers."""
        parser_statuses = {
            'telethon': '📱 Telethon',
            'web': '🌐 Web Scraping',
            'rss': '📡 RSS',
            'telegram_bot': '🤖 Bot API'
        }
        
        message = "📊 Статус парсеров:\n\n"
        for parser_type, parser_name in parser_statuses.items():
            try:
                parser = self.channel_reader.parser_manager.get_parser(parser_type)
                if parser:
                    is_available = await parser.check_availability()
                    status = "✅ Доступен" if is_available else "❌ Недоступен"
                else:
                    # telegram_bot is conceptual, always available if bot is running
                    status = "✅ Доступен" if parser_type == 'telegram_bot' else "❌ Не зарегистрирован"
            except Exception as e:
                logger.error(f"Error checking {parser_type}: {e}")
                status = "❌ Ошибка"
            message += f"{parser_name}: {status}\n"
        
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("🔙 Главное меню", callback_data="main_menu")
        ]])
        await query.edit_message_text(message, reply_markup=keyboard)
    
    async def _check_parser_status(self, query, parser_type: str):
        """Check detailed status of a specific parser."""
        parser = self.channel_reader.parser_manager.get_parser(parser_type)
        if not parser:
            await query.answer(f"Парсер {parser_type} не найден", show_alert=True)
            return
        
        try:
            is_available = await parser.check_availability()
            status = "✅ Доступен и готов к работе" if is_available else "❌ Недоступен"
            await query.answer(status, show_alert=True)
        except Exception as e:
            logger.error(f"Error checking parser {parser_type}: {e}")
            await query.answer(f"❌ Ошибка проверки: {e}", show_alert=True)
    
    async def _show_change_source_menu(self, query, channel_id: int):
        """Show menu for changing channel source."""
        channel = self.db.get_channel_by_id(channel_id)
        if not channel:
            await query.answer("Канал не найден", show_alert=True)
            return
        
        title = channel.get('title', 'N/A')
        current_source = channel.get('source_type', 'telegram_bot')
        source_emoji = {'telethon': '📱', 'web': '🌐', 'rss': '📡', 'telegram_bot': '🤖'}.get(current_source, '📺')
        
        message = f"📺 {title}\n\nТекущий источник: {source_emoji} {current_source}\n\nВыберите новый источник:"
        keyboard = self._create_source_type_keyboard(channel_id, is_change=True)
        await query.edit_message_text(message, reply_markup=keyboard)
    
    async def _confirm_remove_channel(self, query, channel_id: int):
        """Show confirmation dialog for channel removal."""
        channel = self.db.get_channel_by_id(channel_id)
        if not channel:
            await query.answer("Канал не найден", show_alert=True)
            return
        
        title = channel.get('title', 'N/A')
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Да, удалить", callback_data=f"remove_channel:{channel_id}"),
                InlineKeyboardButton("❌ Отмена", callback_data=f"channel_info:{channel_id}")
            ]
        ])
        await query.edit_message_text(
            f"⚠️ Вы уверены, что хотите удалить канал '{title}'?",
            reply_markup=keyboard
        )
    
    async def _handle_remove_channel(self, query, channel_id: int):
        """Handle channel removal."""
        channel = self.db.get_channel_by_id(channel_id)
        if not channel:
            await query.answer("Канал не найден", show_alert=True)
            return
        
        title = channel.get('title', 'N/A')
        success = self.db.remove_channel(channel_id)
        self._remove_channel_from_json(channel_id)
        
        if success:
            logger.info(f"Channel removed: ID {channel_id}")
            await query.edit_message_text(f"✅ Канал '{title}' успешно удален!")
            
            # Show channels list after removal
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 К каналам", callback_data="list_channels")
            ]])
            await query.message.reply_text("Выберите действие:", reply_markup=keyboard)
        else:
            await query.edit_message_text("❌ Ошибка при удалении канала.")
    
    async def _show_add_sources_menu(self, update: Update):
        """Show menu for adding sources."""
        message = "➕ Добавление источников\n\nВыберите способ добавления:"
        keyboard = self._create_add_sources_keyboard()
        await update.message.reply_text(message, reply_markup=keyboard)
    
    async def _show_news_period_menu(self, update: Update):
        """Show menu for selecting news period."""
        message = "📰 Получить новости\n\nВыберите период:"
        keyboard = self._create_period_keyboard()
        await update.message.reply_text(message, reply_markup=keyboard)
    
    async def _show_settings_menu(self, update: Update):
        """Show settings menu."""
        message = "⚙️ Настройки\n\nВыберите опцию:"
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📊 Статус парсеров", callback_data="parsers_status")],
            [InlineKeyboardButton("🔙 Главное меню", callback_data="main_menu")]
        ])
        await update.message.reply_text(message, reply_markup=keyboard)
    
    async def _show_main_menu_inline(self, query):
        """Show main menu as inline message."""
        message = "👋 Главное меню\n\nВыберите действие:"
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Добавить источники", callback_data="default_sources_menu")],
            [InlineKeyboardButton("📰 Получить новости", callback_data="show_news_period")],
            [InlineKeyboardButton("📋 Мои источники", callback_data="list_channels")],
            [InlineKeyboardButton("📊 Статистика", callback_data="global_stats")]
        ])
        await query.edit_message_text(message, reply_markup=keyboard)
    
    async def _show_categories_menu(self, query):
        """Show categories menu."""
        categories = self.default_sources.get("categories", {})
        if not categories:
            await query.edit_message_text("❌ Предустановленные источники не найдены.")
            return
        
        message = "📚 Категории источников\n\nВыберите категорию:"
        keyboard = self._create_categories_keyboard()
        await query.edit_message_text(message, reply_markup=keyboard)
    
    async def _show_category_sources(self, query, category_id: str):
        """Show sources in a category."""
        categories = self.default_sources.get("categories", {})
        category_data = categories.get(category_id, {})
        
        if not category_data:
            await query.answer("Категория не найдена", show_alert=True)
            return
        
        category_name = category_data.get("name", category_id)
        sources = category_data.get("sources", [])
        
        message = f"{category_name}\n\nДоступные источники:\n\n"
        
        # Build a set of existing channel IDs for fast lookup
        all_channels = self.db.get_all_channels()
        existing_channel_ids = {ch.get('channel_id') for ch in all_channels}
        
        for source in sources:
            title = source.get("title", "Unknown")
            username = source.get("username", "")
            source_type = source.get("source_type", "rss")
            source_config = source.get("source_config", {})
            
            # Check if source is already added by computing channel_id the same way we do when adding
            is_added = False
            if source_type == "rss" and source_config.get("rss_url"):
                # For RSS, channel_id is hash of rss_url
                rss_url = source_config.get("rss_url")
                channel_id = stable_source_id(rss_url, "rss")
                is_added = channel_id in existing_channel_ids
            else:
                # For other sources, channel_id is hash of username
                channel_id = stable_source_id(username, source_type)
                is_added = channel_id in existing_channel_ids
            
            status = "✅ Добавлен" if is_added else "➕ Добавить"
            message += f"• {title} - {status}\n"
        
        keyboard = self._create_category_sources_keyboard(category_id)
        try:
            await query.edit_message_text(message, reply_markup=keyboard)
        except Exception as e:
            # If message is not modified (same content), that's fine - just answer the callback
            error_msg = str(e).lower()
            if "not modified" in error_msg or "message is not modified" in error_msg:
                # Message content is the same - this is OK, just acknowledge
                await query.answer()
            else:
                # Re-raise other exceptions
                logger.error(f"Error updating category sources message: {e}")
                raise
    
    async def _handle_add_default_source(self, query, category_id: str, username: str):
        """Handle adding a default source."""
        categories = self.default_sources.get("categories", {})
        category_data = categories.get(category_id, {})
        sources = category_data.get("sources", [])
        
        # Find the source
        source_data = None
        for source in sources:
            if source.get("username") == username:
                source_data = source
                break
        
        if not source_data:
            await query.answer("Источник не найден", show_alert=True)
            return
        
        title = source_data.get("title", username)
        source_type = source_data.get("source_type", "rss")
        source_config = source_data.get("source_config", {})
        
        # For RSS sources, use rss_url as username if available
        if source_type == "rss" and source_config.get("rss_url"):
            # Use RSS URL as the identifier for RSS parser
            username = source_config.get("rss_url")
        
        # Generate channel_id (hash of username/url)
        channel_id = stable_source_id(username, source_type)
        
        # Check if already exists
        existing = self.db.get_channel_by_id(channel_id)
        if existing:
            await query.answer(f"✅ {title} уже добавлен", show_alert=True)
            return
        
        # Add to database
        success = self.db.add_channel(channel_id, username, title, source_type=source_type)
        if success and source_config:
            self.db.update_channel_source_type(channel_id, source_type, source_config)
        
        if success:
            logger.info(f"Default source added: {title} (@{username}, ID: {channel_id}, source: {source_type})")
            source_emoji = {'telethon': '📱', 'web': '🌐', 'rss': '📡', 'telegram_bot': '🤖'}.get(source_type, '📺')
            await query.answer(f"✅ {title} добавлен ({source_emoji})", show_alert=True)
            # Refresh the category sources list
            await self._show_category_sources(query, category_id)
        else:
            await query.answer("❌ Ошибка при добавлении", show_alert=True)
    
    async def _handle_add_manual_source(self, query):
        """Handle manual source addition."""
        await query.edit_message_text(
            "🔗 Добавление источника вручную\n\n"
            "Введите username канала или RSS ссылку:\n\n"
            "Примеры:\n"
            "• @channel_name\n"
            "• https://t.me/channel_name\n"
            "• https://example.com/rss\n\n"
            "Или используйте команду: /add_channel <ссылка>"
        )
    
    async def periodic_check(self):
        """Periodically parse configured sources."""
        channels = self.db.get_all_channels()
        if not channels:
            return

        parse_limit = config.get_auto_parse_limit()
        parse_days = config.get_auto_parse_days()
        total = {'parsed': 0, 'skipped': 0, 'errors': 0}
        for channel in channels:
            try:
                stats = await self.channel_reader.force_parse_channel(
                    bot=self.app.bot if self.app else None,
                    channel_id=channel.get('channel_id'),
                    channel_username=channel.get('username'),
                    limit=parse_limit,
                    days=parse_days,
                )
                for key in total:
                    total[key] += stats.get(key, 0)
            except Exception as e:
                logger.error(f"Error parsing channel {channel.get('channel_id')}: {e}")
                total['errors'] += 1
        logger.info(f"Periodic parsing finished: {total}")
    
    def run(self):
        """Run the bot."""
        token = config.get_bot_token()
        if not token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN is not set. Configure it via the admin panel or .env file.")

        async def post_init(application):
            if config.get_auto_parse_enabled():
                self.scheduler.start(self.periodic_check)

        async def post_shutdown(application):
            self.scheduler.stop()
            await self.channel_reader.parser_manager.close_all()

        # Create application
        self.app = (
            Application.builder()
            .token(token)
            .post_init(post_init)
            .post_shutdown(post_shutdown)
            .build()
        )
        
        # Add handlers
        self.app.add_handler(CommandHandler("start", self.start_command))
        self.app.add_handler(CommandHandler("help", self.help_command))
        self.app.add_handler(CommandHandler("add_channel", self.add_channel_command))
        self.app.add_handler(CommandHandler("remove_channel", self.remove_channel_command))
        self.app.add_handler(CommandHandler("list_channels", self.list_channels_command))
        self.app.add_handler(CommandHandler("get_news", self.get_news_command))
        
        # Handle callback queries (inline buttons)
        self.app.add_handler(CallbackQueryHandler(self.button_handler))
        
        # Handle text messages (reply keyboard buttons)
        self.app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_text_message)
        )
        
        # Handle channel messages
        # IMPORTANT: In python-telegram-bot 20.7, MessageHandler with ChatType.CHANNEL
        # should handle channel_post automatically, but it may not work correctly.
        # We add an explicit handler for channel_post as fallback using TypeHandler
        async def handle_channel_post_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
            """Handle channel_post updates explicitly."""
            if update.channel_post:
                await self.handle_channel_message(update, context)
        
        # Add TypeHandler to catch channel_post updates explicitly (group=-1 to run first)
        self.app.add_handler(TypeHandler(Update, handle_channel_post_update), group=-1)
        
        # Handle channel posts via MessageHandler (should work but may not)
        self.app.add_handler(
            MessageHandler(
                filters.ChatType.CHANNEL,
                self.handle_channel_message
            )
        )
        
        # Handle supergroup messages (these come as message, not channel_post)
        self.app.add_handler(
            MessageHandler(
                filters.ChatType.SUPERGROUP,
                self.handle_channel_message
            )
        )
        
        # Start scheduler (for periodic tasks if needed)
        # self.scheduler.start(self.periodic_check)
        
        # Run bot
        logger.info("Bot is starting...")
        self.app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    bot = NewsBot()
    bot.run()

