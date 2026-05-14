# Security Policy

## Supported Versions

Security fixes are handled on the default branch.

## Secrets and Local Data

Do not commit `.env`, SQLite databases, Telethon session files, logs, browser caches, or generated exports from the admin panel. The repository `.gitignore` and `.dockerignore` exclude the common local paths, but review `git status --ignored` before publishing.

Use `.env.example` as the public template and keep real Telegram, Telethon, and LM Studio credentials only in local `.env` files or the runtime database.

## Reporting

Please report security issues privately to the repository maintainer instead of opening a public issue with exploit details or live credentials.

