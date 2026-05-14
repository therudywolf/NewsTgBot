# 🐺 NewsTgBot

> Wolf-built self-hosted news aggregator for Telegram and the web.

![Version](https://img.shields.io/badge/version-0.6.0--beta.1-4c8bf5)
![Status](https://img.shields.io/badge/status-beta-f59e0b)
[![License](https://img.shields.io/badge/license-AGPL--3.0--only-22c55e)](LICENSE)

Self-hosted IT news aggregator with a web admin panel, Telegram bot, multi-source parsers, and local LLM summarization.

## Features

- **Web admin panel** at `http://localhost:8000` — full bot configuration, source management, news viewer, LLM summary
- **Bot settings from UI** — Telegram Bot API token, Telethon credentials, auto-parse schedule — all configurable and persisted without editing `.env`
- **LM Studio integration** — native `/api/v1` and OpenAI-compatible `/v1` modes for model discovery, loading and chat
- **Telegram user-account parser** — login via code/2FA, browse your channels, add them in one click
- **RSS parser** — 23 built-in IT/security/engineering RSS feeds, plus any custom URL
- **Web scraper** — Playwright-based parser for public Telegram channel pages
- **Telegram Bot API worker** — inline keyboard menus, commands, real-time channel post capture
- **LLM deduplication & aggregation** — automatic duplicate removal and structured news summary in Russian
- **SQLite storage** — channels, news, tags, sessions, app settings
- **Docker Compose** — panel + bot as separate services sharing a data volume
- **`.env` export** — generate a ready-to-use `.env` file from the admin panel

## Quick Start

### Using Docker (Recommended)

```bash
# Clone the repository
git clone https://github.com/therudywolf/NewsTgBot.git
cd NewsTgBot

# Copy and edit the example environment file
cp .env.example .env
# Edit .env with your tokens if you already have them (optional)

# Create required directories
mkdir -p data logs

# Build and start services
docker compose up --build
```

Open the admin panel at: **http://localhost:8000**

> ℹ️ The Telegram bot worker starts only when `TELEGRAM_BOT_TOKEN` is set (via `.env` or the web panel). The admin panel works without it.

## Configuration

All settings can be entered through the web panel (section **Настройки бота**) and are persisted in the database. The `.env` file serves as an initial default.

### Telegram Bot API

```env
TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
```

### Telegram user-account parser (Telethon)

Create `api_id` / `api_hash` at <https://my.telegram.org>.

```env
TELETHON_API_ID=12345678
TELETHON_API_HASH=your_telethon_api_hash
TELETHON_PHONE=+79990000000
```

### LM Studio

```env
LM_STUDIO_BASE_URL=http://10.77.77.2:29931
LM_STUDIO_API_TOKEN=
LM_STUDIO_MODEL=
LM_STUDIO_API_MODE=native
```

### Auto-parse

```env
AUTO_PARSE_ENABLED=false
CHECK_INTERVAL_SECONDS=3600
AUTO_PARSE_LIMIT=200
AUTO_PARSE_DAYS=7
```

See `.env.example` for all available variables.

## Bot commands

| Command | Description |
|---|---|
| `/start` | Main menu with reply keyboard |
| `/add_channel <link>` | Add a channel or RSS source |
| `/remove_channel <link or ID>` | Remove a source |
| `/list_channels` | List tracked sources |
| `/get_news 1d\|7d\|30d` | LLM news summary for a period |
| `/help` | Help |

## Admin panel API

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/status` | Global stats and config |
| `GET/POST` | `/api/bot-settings` | Read / update bot token, Telethon, auto-parse |
| `GET/POST` | `/api/settings` | Read / update LM Studio settings |
| `GET` | `/api/env-export` | Generate `.env` from current config |
| `GET/POST` | `/api/lm-studio/models` | List / load / select / test LM Studio models |
| `GET/POST` | `/api/telegram/*` | Telethon login, channel discovery |
| `GET/POST/DELETE` | `/api/sources/*` | CRUD for news sources, parse triggers |
| `GET` | `/api/default-sources` | Built-in RSS catalog |
| `GET/POST` | `/api/news/*` | News list and LLM summary |

## Project structure

```
bot.py                  Telegram Bot API worker
web_app.py              FastAPI admin panel backend
web/                    Static admin panel (HTML/CSS/JS)
llm_client.py           LM Studio client (native + OpenAI)
telegram_account.py     Telethon login / channel discovery
channel_reader.py       Channel message processing and parsing
parsers/                RSS, Telethon, web scraping parsers
database.py             SQLite schema and repository
config.py               Environment + DB-backed configuration
source_identity.py      Deterministic source IDs
deduplicator.py         LLM-based news deduplication
scheduler.py            Periodic parse scheduler
default_sources.json    Built-in RSS feeds (23 sources, 5 categories)
migrate_add_source_type.py  DB migration script
tests/                  Unit tests
docker-compose.yml      Panel + bot services
Dockerfile              Python 3.11 + Playwright + Chromium
```

## Local development (without Docker)

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m playwright install chromium

# Start the admin panel
uvicorn web_app:app --host 0.0.0.0 --port 8000

# In a separate terminal — start the bot (requires TELEGRAM_BOT_TOKEN)
python bot.py
```

## Tests

```bash
python -m pytest tests/ -v
```

## Development & Contribution

This is a FOSS project under the **GNU Affero General Public License v3 (AGPL-3.0)**.

### Network Copyleft Clause
If you run a modified version of NewsTgBot as a networked service, you **must** provide users access to your modified source code. This ensures the freedom principles of FOSS are maintained.

### Contributing
- Report bugs and feature requests via GitHub Issues
- Submit improvements via Pull Requests
- Maintain AGPL-3.0 compliance in any modifications
- Follow the existing code style and patterns

## Important Notes

- RSS and public web pages are used without paid APIs
- The Telegram user-account parser uses the official MTProto Client API and requires your own `api_id` / `api_hash` from [my.telegram.org](https://my.telegram.org)
- `.env`, `data/`, logs, SQLite databases and Telethon session files are excluded from git (see `.gitignore`)
- After changing the bot token in the admin panel, restart the `bot` container to apply changes
- No personal data, API keys, or tokens are committed to the repository
- All settings are persisted in the SQLite database within the `data/` directory

## License

This project is licensed under the **GNU Affero General Public License v3 (AGPL-3.0)**. See the [LICENSE](LICENSE) file for details.

### Key terms:
- **Copyleft**: Any modifications or derivative works must also be released under AGPL-3.0
- **Network Clause**: If you run this software as a service, you must make the source code available to users
- **Attribution**: You must retain copyright and license notices

### For more information:
- Full license text: <https://www.gnu.org/licenses/agpl-3.0.txt>
- License details: <https://www.gnu.org/licenses/agpl-3.0.html>
