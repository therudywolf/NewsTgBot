# Changelog

All notable changes to NewsTgBot will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-05-12

### Added

- Initial release of NewsTgBot
- Web admin panel for bot configuration at `http://localhost:8000`
- Telegram Bot API worker with inline keyboards and commands
- Multi-source news parsers:
  - RSS feed parser (23 built-in IT/security feeds + custom URLs)
  - Telethon (Telegram user account) parser
  - Playwright-based web scraper
- LLM-based news deduplication and summarization (LM Studio integration)
- SQLite database for channels, news, tags, and app settings
- Docker Compose setup (panel + bot as separate services)
- Pre-configured bot commands:
  - `/start` - Main menu
  - `/add_channel` - Add news source
  - `/remove_channel` - Remove source
  - `/list_channels` - Show tracked sources
  - `/get_news` - LLM-generated summary
  - `/help` - Help menu
- FastAPI admin panel with REST API for:
  - Bot settings management
  - Telethon login and channel discovery
  - News source CRUD operations
  - Model loading and testing
  - `.env` file export
- Automatic parse scheduler with configurable intervals
- Support for multiple parser types per source
- Tag-based news organization
- Comprehensive error handling and logging

### Under the Hood

- Python 3.11+ with async/await support
- FastAPI for REST API
- Pydantic for data validation
- Playwright for web scraping
- python-telegram-bot for Telegram integration
- Telethon for Telegram account API
- SQLite for data persistence
- Docker & Docker Compose for containerization

## [Unreleased]

### Planned

- Support for additional news sources (Medium, Dev.to, etc.)
- User-specific news filtering and preferences
- Web UI improvements and dark mode
- Kubernetes deployment support
- Webhook integration for push notifications
- OpenAI/Claude API support for summarization
- Multi-language support
- Export news to Markdown/PDF
- RSS feed generation from parsed news

---

## Version History

### How to Read Version Numbers

Format: `MAJOR.MINOR.PATCH`

- **MAJOR**: Breaking changes, major features
- **MINOR**: New features, backward compatible
- **PATCH**: Bug fixes, minor improvements

### Deprecation Policy

Features deprecated in version N will be removed in version N+2.
Deprecation notices will be logged with `DEPRECATION_WARNING` level.

---

## Contributing

When making changes, please update this file under the `[Unreleased]` section.

Format for new entries:

```markdown
### Added
- New feature description

### Changed
- Modified behavior description

### Fixed
- Bug fix description

### Removed
- Removed feature description

### Security
- Security fix description
```

