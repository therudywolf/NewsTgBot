# Telegram News Aggregator Bot

Telegram бот для агрегации новостей из различных телеграм каналов, удаления дубликатов и создания кратких сводок с использованием LLM.

## Возможности

- 📰 Чтение новостей из множества Telegram каналов
- 🔄 Автоматическое удаление дубликатов с помощью LLM
- 📊 Агрегация новостей за выбранный период времени
- 🤖 Генерация кратких сводок с использованием LLM

## Установка

1. Клонируйте репозиторий:
```bash
git clone <repository-url>
cd NewsTgBot
```

2. Создайте виртуальное окружение:
```bash
python -m venv venv
source venv/bin/activate  # На Windows: venv\Scripts\activate
```

3. Установите зависимости:
```bash
pip install -r requirements.txt
```

4. Создайте файл `.env` на основе `.env.example`:
```bash
cp .env.example .env
```

5. Заполните `.env` файл с вашими настройками:
```
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
LLM_API_URL=your_llm_api_url_here
LLM_MODEL_NAME=your_model_name_here
```

## Использование

Запустите бота:
```bash
python bot.py
```

### Команды бота

- `/start` - приветствие и инструкция
- `/add_channel <ссылка>` - добавить канал для отслеживания
- `/remove_channel <ссылка или ID>` - удалить канал
- `/list_channels` - показать список отслеживаемых каналов
- `/get_news <период>` - получить агрегированные новости за период
  - Примеры: `/get_news 1d`, `/get_news 7d`, `/get_news 2024-01-01:2024-01-07`
- `/help` - справка по командам

## Структура проекта

```
NewsTgBot/
├── bot.py                 # Главный файл бота
├── config.py              # Конфигурация
├── channels.json          # Список каналов
├── database.py            # Работа с SQLite БД
├── channel_reader.py      # Чтение сообщений из каналов
├── deduplicator.py        # Удаление дубликатов через LLM
├── llm_client.py          # Клиент для LLM API
├── scheduler.py           # Планировщик проверки каналов
├── requirements.txt       # Зависимости Python
├── .env.example          # Пример файла с переменными окружения
└── README.md             # Документация
```

## Технологии

- Python 3.8+
- python-telegram-bot - для работы с Telegram API
- SQLite - для хранения новостей
- aiohttp - для асинхронных HTTP запросов к LLM API

## Лицензия

MIT

