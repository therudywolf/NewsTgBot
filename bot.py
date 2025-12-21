"""Main bot file for Telegram News Aggregator."""
import asyncio
import json
import re
from datetime import datetime, timedelta
from typing import List
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import config
import database
import channel_reader
import deduplicator
import llm_client
import scheduler


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
        welcome_message = """
Привет! Я бот для агрегации новостей из Telegram каналов.

Команды:
/start - показать это сообщение
/add_channel <ссылка> - добавить канал для отслеживания
/remove_channel <ссылка или ID> - удалить канал
/list_channels - показать список каналов
/get_news <период> - получить агрегированные новости
/help - подробная справка

Примеры периодов для /get_news:
• /get_news 1d - за последний день
• /get_news 7d - за последнюю неделю
• /get_news 2024-01-01:2024-01-07 - за указанный период
"""
        await update.message.reply_text(welcome_message)
    
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
            await update.message.reply_text(
                f"✅ Канал {title} (@{username}) успешно добавлен!"
            )
        else:
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
            await update.message.reply_text("✅ Канал успешно удален!")
        else:
            await update.message.reply_text("⚠️ Канал не найден в списке.")
    
    async def list_channels_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /list_channels command."""
        channels = self.db.get_all_channels()
        
        if not channels:
            await update.message.reply_text("Список каналов пуст.")
            return
        
        message = "📋 Отслеживаемые каналы:\n\n"
        for idx, channel in enumerate(channels, 1):
            username = channel.get('username', 'N/A')
            title = channel.get('title', 'N/A')
            channel_id = channel.get('channel_id', 'N/A')
            message += f"{idx}. {title} (@{username})\n   ID: {channel_id}\n\n"
        
        await update.message.reply_text(message)
    
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
            await processing_msg.edit_text(f"🔍 Найдено {len(news_items)} новостей. Удаляю дубликаты...")
            unique_news = await self.deduplicator.deduplicate(news_items)
            
            if not unique_news:
                await processing_msg.edit_text("После удаления дубликатов новостей не осталось.")
                return
            
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
            await processing_msg.edit_text(f"❌ Ошибка при обработке новостей: {e}")
            print(f"Error in get_news_command: {e}")
    
    async def handle_channel_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle messages from channels."""
        if not update.message:
            return
        
        # Process channel message
        await self.channel_reader.process_channel_message(update.message)
    
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
        
        # Handle channel messages (messages from channels/groups)
        self.app.add_handler(
            MessageHandler(
                filters.ChatType.CHANNELS | filters.ChatType.GROUPS,
                self.handle_channel_message
            )
        )
        
        # Start scheduler (for periodic tasks if needed)
        # self.scheduler.start(self.periodic_check)
        
        # Run bot
        print("Bot is starting...")
        self.app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    bot = NewsBot()
    bot.run()

