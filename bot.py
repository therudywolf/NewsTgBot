"""Main bot file for Telegram News Aggregator."""
import asyncio
import json
import logging
import re
from datetime import datetime, timedelta
from typing import List, Dict
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes, TypeHandler
import config
import database
import channel_reader
import deduplicator
import llm_client
import scheduler

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
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command."""
        welcome_message = """Привет! Я бот для агрегации новостей из Telegram каналов.

Используй кнопки ниже для навигации или команды для быстрого доступа."""
        
        keyboard = self._create_main_keyboard()
        await update.message.reply_text(
            welcome_message,
            reply_markup=keyboard
        )
    
    def _create_main_keyboard(self) -> ReplyKeyboardMarkup:
        """Create main reply keyboard."""
        keyboard = [
            ["📋 Каналы", "🔍 Поиск каналов"],
            ["📰 Новости", "🏷️ Теги"],
            ["⚙️ Настройки", "📊 Статистика"]
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
                InlineKeyboardButton("❌ Удалить", callback_data=f"confirm_remove:{channel_id}"),
                InlineKeyboardButton("🔙 Назад", callback_data="list_channels")
            ]
        ]
        return InlineKeyboardMarkup(buttons)
    
    def _create_period_keyboard(self) -> InlineKeyboardMarkup:
        """Create inline keyboard for period selection."""
        buttons = [
            [
                InlineKeyboardButton("1 день", callback_data="period:1d"),
                InlineKeyboardButton("7 дней", callback_data="period:7d"),
                InlineKeyboardButton("30 дней", callback_data="period:30d")
            ],
            [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
        ]
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
        
        buttons.append([InlineKeyboardButton("🔙 Назад", callback_data="main_menu")])
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
        
        # Try to get channel chat info
        try:
            chat = await context.bot.get_chat(f"@{username}" if username else channel_input)
            channel_id = chat.id
            title = chat.title or username
        except Exception as e:
            await update.message.reply_text(
                f"Ошибка при добавлении канала: {e}\n"
                "Убедитесь, что:\n"
                "1. Канал существует\n"
                "2. Бот добавлен в канал\n"
                "3. Вы указали правильную ссылку"
            )
            return
        
        # Add to database
        success = self.db.add_channel(channel_id, username, title)
        
        # Also add to channels.json
        self._add_channel_to_json(channel_id, username, title)
        
        if success:
            logger.info(f"Channel added: {title} (@{username}, ID: {channel_id})")
            await update.message.reply_text(
                f"✅ Канал {title} (@{username}) успешно добавлен!"
            )
        else:
            logger.warning(f"Channel already exists: {title} (@{username}, ID: {channel_id})")
            await update.message.reply_text(
                f"⚠️ Канал уже был добавлен ранее."
            )
    
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
        except:
            # Try as numeric ID
            try:
                channel_id = int(channel_input)
            except:
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
        
        # #region agent log
        import json; f = open('c:\\Users\\rudywolf\\Workspace\\NewsTgBot\\.cursor\\debug.log', 'a', encoding='utf-8'); f.write(json.dumps({"sessionId": "debug-session", "runId": "run1", "hypothesisId": "C", "location": "bot.py:362", "message": "handle_channel_message entry", "data": {"has_message": update.message is not None, "has_channel_post": update.channel_post is not None, "has_processed_message": message is not None, "chat_id": message.chat.id if message and message.chat else None, "chat_type": str(message.chat.type) if message and message.chat else None}, "timestamp": int(__import__('time').time() * 1000)}) + '\n'); f.close()
        # #endregion
        
        if not message:
            # #region agent log
            f = open('c:\\Users\\rudywolf\\Workspace\\NewsTgBot\\.cursor\\debug.log', 'a', encoding='utf-8'); f.write(json.dumps({"sessionId": "debug-session", "runId": "run1", "hypothesisId": "C", "location": "bot.py:369", "message": "handle_channel_message: no message", "data": {}, "timestamp": int(__import__('time').time() * 1000)}) + '\n'); f.close()
            # #endregion
            return
        
        # Process channel message
        result = await self.channel_reader.process_channel_message(message)
        
        # #region agent log
        f = open('c:\\Users\\rudywolf\\Workspace\\NewsTgBot\\.cursor\\debug.log', 'a', encoding='utf-8'); f.write(json.dumps({"sessionId": "debug-session", "runId": "run1", "hypothesisId": "C", "location": "bot.py:377", "message": "handle_channel_message: process result", "data": {"result": result, "message_id": message.message_id, "chat_id": message.chat.id}, "timestamp": int(__import__('time').time() * 1000)}) + '\n'); f.close()
        # #endregion
    
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
            except:
                return None, None
        
        return None, None
    
    def _add_channel_to_json(self, channel_id: int, username: str, title: str):
        """Add channel to channels.json."""
        try:
            with open(config.CHANNELS_JSON_PATH, 'r', encoding='utf-8') as f:
                channels = json.load(f)
        except:
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
        except:
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
            await query.message.reply_text(
                "Главное меню",
                reply_markup=self._create_main_keyboard()
            )
            await query.message.delete()
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
            InlineKeyboardButton("🔙 Назад", callback_data="main_menu")
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
        
        if text == "📋 Каналы":
            await self._show_channels_list(update)
        elif text == "🔍 Поиск каналов":
            await update.message.reply_text(
                "🔍 Поиск каналов\n\n"
                "Введите username канала (например: @channel_name) или ссылку (https://t.me/channel_name) "
                "для добавления канала в отслеживание.\n\n"
                "Также можно использовать команду: /add_channel <ссылка>"
            )
        elif text == "📰 Новости":
            keyboard = self._create_period_keyboard()
            await update.message.reply_text("Выберите период для новостей:", reply_markup=keyboard)
        elif text == "🏷️ Теги":
            await self._show_tags_list_text(update)
        elif text == "⚙️ Настройки":
            await update.message.reply_text("Настройки пока не доступны.")
        elif text == "📊 Статистика":
            await self._show_global_stats_text(update)
        else:
            # Try to search/add channel
            await self._try_add_channel(update, text)
    
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
        # Similar to add_channel_command but from text
        channel_input = text.strip()
        
        # Try to extract channel username or ID
        username = None
        if channel_input.startswith("https://t.me/"):
            username = channel_input.replace("https://t.me/", "").lstrip("/")
        elif channel_input.startswith("@"):
            username = channel_input.lstrip("@")
        else:
            username = channel_input
        
        try:
            chat = await update.message.bot.get_chat(f"@{username}" if username else channel_input)
            channel_id = chat.id
            title = chat.title or username
            
            success = self.db.add_channel(channel_id, username, title, source_type='telegram_bot')
            self._add_channel_to_json(channel_id, username, title)
            
            if success:
                await update.message.reply_text(f"✅ Канал {title} добавлен!")
            else:
                await update.message.reply_text("⚠️ Канал уже был добавлен ранее.")
        except Exception as e:
            await update.message.reply_text(f"Ошибка: {e}")
    
    async def periodic_check(self):
        """Periodic check for new messages (placeholder - messages come via handlers)."""
        # In practice, messages are processed via handle_channel_message
        # This is a placeholder for any periodic maintenance tasks
        pass
    
    def run(self):
        """Run the bot."""
        # Create application
        self.app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
        
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
                # #region agent log
                import json; f = open('c:\\Users\\rudywolf\\Workspace\\NewsTgBot\\.cursor\\debug.log', 'a', encoding='utf-8'); f.write(json.dumps({"sessionId": "debug-session", "runId": "run1", "hypothesisId": "B", "location": "bot.py:834", "message": "TypeHandler caught channel_post", "data": {"has_channel_post": update.channel_post is not None, "chat_id": update.channel_post.chat.id if update.channel_post and update.channel_post.chat else None}, "timestamp": int(__import__('time').time() * 1000)}) + '\n'); f.close()
                # #endregion
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

