# Contributing to NewsTgBot

Thank you for your interest in contributing to NewsTgBot! This project is **AGPL-3.0-or-later** free software. Contributions must be compatible with that license.

## Quick Start

### Prerequisites

- Python 3.11+
- Docker & Docker Compose (for testing)
- Git with pre-commit hooks

### Setup

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install -r requirements-dev.txt
pre-commit install
python -m playwright install chromium
cp .env.example .env  # Configure with your tokens
```

## Contribution Checklist

Before submitting a Pull Request:

- ✅ Tests pass: `pytest tests/ -v`
- ✅ Code formatted: `black . && isort .`
- ✅ Linting: `flake8 .` (should show no errors)
- ✅ Type hints: `mypy . --ignore-missing-imports`
- ✅ Docker config valid: `docker compose config`
- ✅ No secrets in git (pre-commit will catch this)
- ✅ Updated documentation if behavior changed
- ✅ Commit messages follow semantic format (see below)

## Commit Message Format

Use semantic versioning in commit messages:

```
<type>(<scope>): <description>
```

**Types:** `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`

**Examples:**
- `feat(parser): add Bluesky RSS support`
- `fix(bot): handle missing channel ID gracefully`
- `docs(readme): clarify LM Studio setup steps`
- `test(database): add migration tests`

## Code Quality Standards

### Python Style (PEP 8 + Black)

- Line length: max 120 chars
- Use type hints
- Add docstrings to public functions
- 4-space indentation

### Error Handling

✅ **Use specific exceptions:**
```python
try:
    response = requests.get(url, timeout=30)
    response.raise_for_status()
except requests.Timeout:
    logger.warning(f"Timeout: {url}")
except requests.HTTPError as e:
    logger.error(f"HTTP error: {e}")
```

❌ **Avoid bare except:**
```python
try:
    something()
except:  # NO!
    pass
```

### Logging (not print)

```python
import logging
logger = logging.getLogger(__name__)
logger.info("Message")
logger.error("Error occurred")
```

## Testing

### Requirements

- Minimum 70% code coverage
- Critical paths: 90%+ coverage
- New features must include tests

### Run Tests

```bash
pytest tests/ -v                    # All tests
pytest tests/ --cov=.              # With coverage
pytest tests/test_core.py -v        # Single file
```

### Test Example

```python
import pytest
from unittest.mock import Mock, patch

class TestParser:
    """Tests for RSS parser."""
    
    def test_parse_valid_feed(self):
        """Test parsing valid RSS feed."""
        # Arrange
        url = "https://example.com/feed.xml"
        
        # Act
        result = parse_feed(url)
        
        # Assert
        assert len(result) > 0
        assert "title" in result[0]
```

## Security

### Report Vulnerabilities Privately

Email: **[your-security-email@example.com](mailto:your-security-email@example.com)**

**Never** open a GitHub issue for security vulnerabilities!

### Security Best Practices

- ❌ Never commit tokens, passwords, or API keys
- ❌ Never commit database files or `.session` files
- ✅ Use `.env` files for secrets (excluded from git)
- ✅ Validate user input before processing
- ✅ Use parameterized queries (SQL injection prevention)
- ✅ Keep dependencies updated
- ✅ Use HTTPS for external requests

## Docker Development

```bash
# Build images
docker compose build

# Run with logs
docker compose up

# Run tests in Docker
docker compose run web pytest tests/ -v

# Access container
docker compose exec web bash
```

## Documentation

Update docs if you:
- Add or remove features
- Change configuration options
- Modify APIs or endpoints
- Add environment variables

### Document Format

```markdown
## Feature Name

Brief description.

### Configuration

\`\`\`env
NEW_VAR=value
\`\`\`

### Usage

\`\`\`python
from module import function
result = function(param)
\`\`\`
```

## Directory Structure

```
NewsTgBot/
├── bot.py                 # Telegram bot worker
├── web_app.py            # FastAPI admin panel
├── database.py           # SQLite management
├── config.py             # Configuration
├── parsers/              # News source parsers
├── web/                  # Frontend (HTML/CSS/JS)
├── tests/                # Unit tests
├── .github/workflows/    # CI/CD pipelines
└── README.md             # User documentation
```

## Questions?

- 🔍 Check [existing issues](https://github.com/yourusername/NewsTgBot/issues)
- 💬 Start a [discussion](https://github.com/yourusername/NewsTgBot/discussions)

---

**Thank you for contributing to NewsTgBot! 🚀**

