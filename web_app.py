"""FastAPI admin panel for NewsTgBot.

NewsTgBot - Self-hosted IT news aggregator
Copyright (C) 2026 therudywolf

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published
by the Free Software Foundation, either version 3 of the License.
See LICENSE file for details.
"""

from __future__ import annotations

import json
import logging
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta
from pathlib import Path
from threading import Lock
from typing import Any, Deque, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from starlette.middleware.sessions import SessionMiddleware

import config
from auth import ensure_session_secret, hash_password, is_admin_configured, verify_password
from channel_reader import ChannelReader
from database import Database
from deduplicator import Deduplicator
from llm_client import LLMClient
import pipeline_executor
from pipeline_scheduler import PipelineScheduler, validate_cron
import poster
from source_identity import stable_source_id
from telegram_account import TelegramAccountService

logger = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).resolve().parent
STATIC_DIR = ROOT_DIR / "web"

db = Database()
channel_reader = ChannelReader(db)
telegram_account = TelegramAccountService()
pipeline_scheduler = PipelineScheduler(db, channel_reader, telegram_account)

app = FastAPI(title="NewsTgBot Admin", version="0.2.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

PUBLIC_PATHS = {
    "/",
    "/api/health",
    "/api/auth/status",
    "/api/auth/login",
    "/api/auth/logout",
    "/api/setup/status",
    "/api/setup",
}

# Sensitive endpoints get a per-IP sliding-window rate limit. The window and
# max-attempts values are deliberately tight to slow down credential stuffing
# and admin-setup spam without blocking legitimate users.
_RATE_LIMIT_WINDOW_SECONDS = 60
_RATE_LIMITED_PATHS: Dict[str, int] = {
    "/api/auth/login": 8,
    "/api/setup": 5,
}
_rate_limit_state: Dict[str, Dict[str, Deque[float]]] = defaultdict(
    lambda: defaultdict(deque)
)
_rate_limit_lock = Lock()

_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
}


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()
    client = request.client
    return client.host if client else "unknown"


def _rate_limit_check(path: str, ip: str, limit: int) -> bool:
    now = time.monotonic()
    cutoff = now - _RATE_LIMIT_WINDOW_SECONDS
    with _rate_limit_lock:
        bucket = _rate_limit_state[path][ip]
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= limit:
            return False
        bucket.append(now)
        return True


class AuthSetupPayload(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=10, max_length=256)


class AuthLoginPayload(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class SettingsPayload(BaseModel):
    lm_studio_base_url: Optional[str] = None
    lm_studio_model: Optional[str] = None
    lm_studio_api_mode: Optional[str] = Field(default=None, pattern="^(native|openai)$")
    lm_studio_api_token: Optional[str] = None
    web_parser_engine: Optional[str] = Field(default=None, pattern="^(playwright|selenium)$")
    web_parser_headless: Optional[bool] = None
    web_parser_timeout: Optional[int] = Field(default=None, ge=1)
    parser_priority: Optional[List[str]] = None
    log_level: Optional[str] = Field(default=None, pattern="^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$")

    @field_validator("parser_priority")
    @classmethod
    def validate_parser_priority(cls, value: Optional[List[str]]):
        if value is None:
            return value
        normalized = [str(item).strip().lower() for item in value if str(item).strip()]
        allowed = {"telethon", "rss", "web"}
        if not normalized:
            raise ValueError("parser_priority must not be empty")
        if any(item not in allowed for item in normalized):
            raise ValueError("parser_priority contains unsupported parser")
        return normalized


class BotSettingsPayload(BaseModel):
    telegram_bot_token: Optional[str] = None
    auto_parse_enabled: Optional[bool] = None
    check_interval_seconds: Optional[int] = Field(default=None, ge=60)
    auto_parse_limit: Optional[int] = Field(default=None, ge=1)
    auto_parse_days: Optional[int] = Field(default=None, ge=1)
    telethon_api_id: Optional[str] = None
    telethon_api_hash: Optional[str] = None
    telethon_phone: Optional[str] = None


class LoadModelPayload(BaseModel):
    model: str
    context_length: Optional[int] = None
    flash_attention: Optional[bool] = None


class TelegramSendCodePayload(BaseModel):
    phone: str


class TelegramSignInPayload(BaseModel):
    phone: str
    code: str
    password: Optional[str] = None
    phone_code_hash: Optional[str] = None


class TelegramChannelPayload(BaseModel):
    id: int
    username: Optional[str] = None
    title: str


class TelegramChannelsPayload(BaseModel):
    channels: List[TelegramChannelPayload]


class ManualSourcePayload(BaseModel):
    value: str
    title: Optional[str] = None
    source_type: str = Field(default="rss", pattern="^(rss|web|telethon|telegram_bot)$")


class DefaultSourcePayload(BaseModel):
    title: str
    username: str
    source_type: str = Field(default="rss", pattern="^(rss|web|telethon|telegram_bot)$")
    source_config: Dict[str, Any] = Field(default_factory=dict)


class SummaryPayload(BaseModel):
    days: int = Field(default=1, ge=1, le=365)


class BotPayload(BaseModel):
    label: str = Field(min_length=1, max_length=128)
    kind: str = Field(default="bot_api", pattern="^(bot_api|telethon)$")
    token: Optional[str] = None
    default_chat_id: Optional[str] = None
    enabled: Optional[bool] = True


class BotUpdatePayload(BaseModel):
    label: Optional[str] = Field(default=None, min_length=1, max_length=128)
    kind: Optional[str] = Field(default=None, pattern="^(bot_api|telethon)$")
    token: Optional[str] = None
    default_chat_id: Optional[str] = None
    enabled: Optional[bool] = None


class PromptPayload(BaseModel):
    task: str = Field(pattern="^(dedup|summary|tags|repost)$")
    name: str = Field(min_length=1, max_length=128)
    system_prompt: str = Field(min_length=1, max_length=8000)
    user_template: str = Field(min_length=1, max_length=12000)
    is_active: bool = False


class PostingPreviewPayload(BaseModel):
    news_ids: Optional[List[int]] = None
    days: Optional[int] = Field(default=None, ge=1, le=365)
    instruction: Optional[str] = Field(default=None, max_length=2000)
    prompt_name: Optional[str] = Field(default=None, max_length=128)


class PostingSendPayload(BaseModel):
    bot_id: int = Field(ge=1)
    text: str = Field(min_length=1, max_length=4096)
    chat_id: Optional[str] = Field(default=None, max_length=128)
    parse_mode: Optional[str] = Field(default=None, pattern="^(Markdown|MarkdownV2|HTML)$")
    disable_web_page_preview: bool = True


class PipelineStepPayload(BaseModel):
    type: str = Field(pattern="^(parse_sources|filter|dedup|summary|compose_post|publish|wait)$")
    params: Dict[str, Any] = Field(default_factory=dict)


class PromptTestPayload(BaseModel):
    system_prompt: str = Field(min_length=1, max_length=8000)
    user_template: str = Field(min_length=1, max_length=12000)
    sample_news: Optional[str] = Field(default=None, max_length=8000)
    instruction: Optional[str] = Field(default=None, max_length=2000)
    period: Optional[str] = Field(default=None, max_length=128)


class PipelineTemplatePayload(BaseModel):
    template: str = Field(pattern="^(full_pipeline|summary_only|repost_only|parse_only)$")
    name: Optional[str] = Field(default=None, max_length=128)


class PipelinePayload(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    group_name: str = Field(default="default", min_length=1, max_length=64)
    enabled: bool = True
    schedule_cron: Optional[str] = Field(default=None, max_length=128)
    steps: List[PipelineStepPayload] = Field(default_factory=list)


def _mask_token(token: str) -> str:
    """Show first 4 and last 4 chars, mask the rest."""
    if not token:
        return ""
    if len(token) <= 10:
        return "*" * len(token)
    return token[:4] + "*" * (len(token) - 8) + token[-4:]


def _apply_log_level(level: str | None = None) -> None:
    logging.getLogger().setLevel((level or config.get_log_level()).upper())


def _write_runtime_env() -> str:
    path = config.write_runtime_env()
    logger.info("Managed runtime env updated at %s", path)
    return path


def _bump_revision(key: str) -> str:
    revision = datetime.now().isoformat()
    db.set_setting(key, revision)
    return revision


def _safe_config() -> Dict[str, Any]:
    bot_token = config.get_bot_token()

    return {
        "database_path": config.DATABASE_PATH,
        "channels_json_path": config.CHANNELS_JSON_PATH,
        "managed_env_path": config.MANAGED_ENV_PATH,
        "telegram_bot_configured": bool(bot_token),
        "telegram_bot_token_masked": _mask_token(bot_token),
        "telethon_configured": bool(config.get_telethon_api_id() and config.get_telethon_api_hash()),
        "telethon_phone": config.get_telethon_phone() or "",
        "lm_studio_base_url": config.get_lm_studio_base_url(),
        "lm_studio_model": config.get_lm_studio_model(),
        "lm_studio_api_mode": config.get_lm_studio_api_mode(),
        "lm_studio_token_configured": bool(config.get_lm_studio_api_token()),
        "auto_parse_enabled": config.get_auto_parse_enabled(),
        "check_interval_seconds": config.get_check_interval(),
        "auto_parse_limit": config.get_auto_parse_limit(),
        "auto_parse_days": config.get_auto_parse_days(),
        "web_parser_engine": config.get_web_parser_engine(),
        "web_parser_headless": config.get_web_parser_headless(),
        "web_parser_timeout": config.get_web_parser_timeout(),
        "parser_priority": config.get_parser_priority(),
        "log_level": config.get_log_level(),
        "admin_username": config.get_admin_username(),
    }


def _llm_client() -> LLMClient:
    return LLMClient(
        api_url=config.get_lm_studio_base_url(),
        model_name=config.get_lm_studio_model(),
        api_token=config.get_lm_studio_api_token(),
        api_mode=config.get_lm_studio_api_mode(),
    )


def _source_identifier(source: DefaultSourcePayload | ManualSourcePayload) -> str:
    if isinstance(source, DefaultSourcePayload):
        if source.source_type == "rss" and source.source_config.get("rss_url"):
            return source.source_config["rss_url"]
        return source.username
    return source.value


def _add_source(
    identifier: str,
    title: str,
    source_type: str,
    source_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    namespace = "rss" if source_type == "rss" else source_type
    channel_id = stable_source_id(identifier, namespace)
    username = identifier.strip()
    success = db.add_channel(channel_id, username, title, source_type=source_type)
    db.update_channel_source_type(channel_id, source_type, source_config or {})
    return {
        "created": success,
        "channel": db.get_channel_by_id(channel_id),
    }


def _is_authenticated(request: Request) -> bool:
    return bool(request.session.get("authenticated"))


@app.middleware("http")
async def admin_auth_middleware(request: Request, call_next):
    path = request.url.path

    rate_limit = _RATE_LIMITED_PATHS.get(path)
    if rate_limit is not None and request.method == "POST":
        ip = _client_ip(request)
        if not _rate_limit_check(path, ip, rate_limit):
            response: Response = JSONResponse(
                {"detail": "Too many requests, slow down"},
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            )
            response.headers["Retry-After"] = str(_RATE_LIMIT_WINDOW_SECONDS)
            for header, value in _SECURITY_HEADERS.items():
                response.headers[header] = value
            return response

    if path.startswith("/static/") or path in PUBLIC_PATHS:
        response = await call_next(request)
    elif path.startswith("/api/") and not is_admin_configured(db):
        response = JSONResponse(
            {"detail": "Admin setup required"},
            status_code=status.HTTP_409_CONFLICT,
        )
    elif path.startswith("/api/") and not _is_authenticated(request):
        response = JSONResponse(
            {"detail": "Authentication required"},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    else:
        response = await call_next(request)

    for header, value in _SECURITY_HEADERS.items():
        response.headers.setdefault(header, value)
    if config.ADMIN_HTTPS_ONLY:
        response.headers.setdefault(
            "Strict-Transport-Security",
            "max-age=31536000; includeSubDomains",
        )
    return response


# SessionMiddleware must be added AFTER @app.middleware("http") decorators.
# Starlette applies middleware in LIFO order, so the last-added middleware
# becomes outermost (runs first). SessionMiddleware needs to wrap auth middleware
# so the session scope is populated before _is_authenticated is called.
app.add_middleware(
    SessionMiddleware,
    secret_key=ensure_session_secret(db),
    same_site="lax",
    https_only=config.ADMIN_HTTPS_ONLY,
    max_age=60 * 60 * 12,
)


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/setup/status")
async def setup_status():
    return {"configured": is_admin_configured(db)}


@app.post("/api/setup")
async def setup_admin(payload: AuthSetupPayload, request: Request):
    if is_admin_configured(db):
        raise HTTPException(status_code=409, detail="Admin is already configured")

    db.set_setting("admin_username", payload.username.strip())
    db.set_setting("admin_password_hash", hash_password(payload.password))
    _write_runtime_env()

    request.session["authenticated"] = True
    request.session["username"] = payload.username.strip()
    return {"configured": True, "username": payload.username.strip()}


@app.get("/api/auth/status")
async def auth_status(request: Request):
    configured = is_admin_configured(db)
    return {
        "configured": configured,
        "authenticated": configured and _is_authenticated(request),
        "username": request.session.get("username") if configured else None,
    }


@app.post("/api/auth/login")
async def login(payload: AuthLoginPayload, request: Request):
    if not is_admin_configured(db):
        raise HTTPException(status_code=409, detail="Admin setup required")

    username = config.get_admin_username()
    password_hash = config.get_admin_password_hash()
    # Always run verify_password to avoid revealing username validity via timing.
    password_ok = verify_password(payload.password, password_hash)
    username_ok = payload.username.strip() == username
    if not (username_ok and password_ok):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    # Rotate the session on successful auth to prevent session fixation.
    request.session.clear()
    request.session["authenticated"] = True
    request.session["username"] = username
    request.session["issued_at"] = int(time.time())
    return {"authenticated": True, "username": username}


@app.post("/api/auth/logout")
async def logout(request: Request):
    request.session.clear()
    return {"authenticated": False}


@app.get("/api/status")
async def status():
    stats = db.get_global_stats()
    return {
        "ok": True,
        "time": datetime.now().isoformat(),
        "config": _safe_config(),
        "stats": stats,
    }


@app.get("/api/health")
async def health():
    return {"ok": True, "time": datetime.now().isoformat()}


@app.get("/api/settings")
async def get_settings():
    return _safe_config()


@app.post("/api/settings")
async def update_settings(payload: SettingsPayload):
    parser_settings_changed = False

    if payload.lm_studio_base_url is not None:
        db.set_setting("lm_studio_base_url", payload.lm_studio_base_url.rstrip("/"))
    if payload.lm_studio_model is not None:
        db.set_setting("lm_studio_model", payload.lm_studio_model)
    if payload.lm_studio_api_mode is not None:
        db.set_setting("lm_studio_api_mode", payload.lm_studio_api_mode)
    if payload.lm_studio_api_token is not None:
        db.set_setting("lm_studio_api_token", payload.lm_studio_api_token.strip())
    if payload.web_parser_engine is not None:
        db.set_setting("web_parser_engine", payload.web_parser_engine)
        parser_settings_changed = True
    if payload.web_parser_headless is not None:
        db.set_setting("web_parser_headless", payload.web_parser_headless)
        parser_settings_changed = True
    if payload.web_parser_timeout is not None:
        db.set_setting("web_parser_timeout", payload.web_parser_timeout)
        parser_settings_changed = True
    if payload.parser_priority is not None:
        db.set_setting("parser_priority", payload.parser_priority)
        parser_settings_changed = True
    if payload.log_level is not None:
        db.set_setting("log_level", payload.log_level.upper())
        _apply_log_level(payload.log_level.upper())

    if parser_settings_changed:
        _bump_revision("parsers_runtime_revision")

    _write_runtime_env()
    return _safe_config()


@app.get("/api/bot-settings")
async def get_bot_settings():
    """Return bot configuration (tokens are masked)."""
    bot_token = config.get_bot_token()
    return {
        "telegram_bot_token_masked": _mask_token(bot_token),
        "telegram_bot_token_configured": bool(bot_token),
        "auto_parse_enabled": config.get_auto_parse_enabled(),
        "check_interval_seconds": config.get_check_interval(),
        "auto_parse_limit": config.get_auto_parse_limit(),
        "auto_parse_days": config.get_auto_parse_days(),
        "telethon_api_id_configured": bool(config.get_telethon_api_id()),
        "telethon_api_hash_configured": bool(config.get_telethon_api_hash()),
        "telethon_phone": config.get_telethon_phone(),
    }


@app.post("/api/bot-settings")
async def update_bot_settings(payload: BotSettingsPayload):
    """Save bot configuration to the database."""
    bot_settings_changed = False
    telethon_settings_changed = False

    if payload.telegram_bot_token is not None:
        db.set_setting("telegram_bot_token", payload.telegram_bot_token.strip())
        bot_settings_changed = True
    if payload.auto_parse_enabled is not None:
        db.set_setting("auto_parse_enabled", payload.auto_parse_enabled)
        bot_settings_changed = True
    if payload.check_interval_seconds is not None:
        db.set_setting("check_interval_seconds", payload.check_interval_seconds)
        bot_settings_changed = True
    if payload.auto_parse_limit is not None:
        db.set_setting("auto_parse_limit", payload.auto_parse_limit)
        bot_settings_changed = True
    if payload.auto_parse_days is not None:
        db.set_setting("auto_parse_days", payload.auto_parse_days)
        bot_settings_changed = True
    if payload.telethon_api_id is not None:
        db.set_setting("telethon_api_id", payload.telethon_api_id.strip())
        telethon_settings_changed = True
    if payload.telethon_api_hash is not None:
        db.set_setting("telethon_api_hash", payload.telethon_api_hash.strip())
        telethon_settings_changed = True
    if payload.telethon_phone is not None:
        db.set_setting("telethon_phone", payload.telethon_phone.strip())
        telethon_settings_changed = True

    if bot_settings_changed:
        _bump_revision("bot_runtime_revision")
    if telethon_settings_changed:
        _bump_revision("parsers_runtime_revision")
        await telegram_account.disconnect()

    _write_runtime_env()
    return await get_bot_settings()


@app.get("/api/env-export")
async def export_env():
    """Return managed env file content for backup/debugging."""
    return {"path": config.MANAGED_ENV_PATH, "content": config.render_runtime_env()}


@app.post("/api/env-sync")
async def sync_env():
    path = _write_runtime_env()
    return {"ok": True, "path": path}


@app.get("/api/lm-studio/models")
async def lm_models():
    try:
        models = await _llm_client().list_models()
        return {"models": models, "settings": _safe_config()}
    except Exception as e:
        logger.error("LM Studio model list failed: %s", e)
        raise HTTPException(status_code=502, detail=str(e))


@app.post("/api/lm-studio/load")
async def lm_load_model(payload: LoadModelPayload):
    try:
        data = await _llm_client().load_model(
            payload.model,
            context_length=payload.context_length,
            flash_attention=payload.flash_attention,
        )
        db.set_setting("lm_studio_model", payload.model)
        _write_runtime_env()
        return {"result": data, "settings": _safe_config()}
    except Exception as e:
        logger.error("LM Studio model load failed: %s", e)
        raise HTTPException(status_code=502, detail=str(e))


@app.post("/api/lm-studio/select")
async def lm_select_model(payload: LoadModelPayload):
    db.set_setting("lm_studio_model", payload.model)
    _write_runtime_env()
    return {"settings": _safe_config()}


@app.post("/api/lm-studio/test")
async def lm_test():
    try:
        return await _llm_client().test_connection()
    except Exception as e:
        logger.error("LM Studio test failed: %s", e)
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/api/telegram/status")
async def telegram_status():
    return await telegram_account.status()


@app.post("/api/telegram/send-code")
async def telegram_send_code(payload: TelegramSendCodePayload):
    try:
        return await telegram_account.send_code(payload.phone)
    except Exception as e:
        logger.error("Telegram send-code failed: %s", e)
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/telegram/sign-in")
async def telegram_sign_in(payload: TelegramSignInPayload):
    try:
        return await telegram_account.sign_in(
            payload.phone,
            payload.code,
            password=payload.password,
            phone_code_hash=payload.phone_code_hash,
        )
    except Exception as e:
        logger.error("Telegram sign-in failed: %s", e)
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/telegram/channels")
async def telegram_channels(limit: int = 300):
    try:
        return {"channels": await telegram_account.list_channels(limit=limit)}
    except Exception as e:
        logger.error("Telegram channel list failed: %s", e)
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/telegram/channels")
async def telegram_add_channels(payload: TelegramChannelsPayload):
    added = []
    for channel in payload.channels:
        identifier = channel.username or str(channel.id)
        created = db.add_channel(
            channel.id,
            identifier,
            channel.title,
            source_type="telethon",
        )
        db.update_channel_source_type(channel.id, "telethon", {"telegram_id": channel.id})
        added.append({"created": created, "channel": db.get_channel_by_id(channel.id)})
    return {"added": added}


@app.get("/api/default-sources")
async def default_sources():
    path = ROOT_DIR / "default_sources.json"
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


@app.get("/api/sources")
async def sources():
    rows = db.get_all_channels()
    for row in rows:
        row["stats"] = db.get_channel_stats(row["channel_id"])
        row["source_config"] = (db.get_channel_source_config(row["channel_id"]) or {}).get("source_config", {})
    return {"sources": rows}


@app.post("/api/sources/default")
async def add_default_source(payload: DefaultSourcePayload):
    identifier = _source_identifier(payload)
    source_config = payload.source_config
    if payload.source_type == "rss" and not source_config.get("rss_url"):
        source_config = {"rss_url": identifier}
    return _add_source(identifier, payload.title, payload.source_type, source_config)


@app.post("/api/sources/manual")
async def add_manual_source(payload: ManualSourcePayload):
    title = payload.title or payload.value
    source_config = {"rss_url": payload.value} if payload.source_type == "rss" else {}
    return _add_source(payload.value, title, payload.source_type, source_config)


@app.delete("/api/sources/{channel_id}")
async def remove_source(channel_id: int):
    return {"removed": db.remove_channel(channel_id)}


@app.post("/api/sources/{channel_id}/parse")
async def parse_source(channel_id: int, limit: int = 200, days: int = 7):
    channel = db.get_channel_by_id(channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Source not found")

    stats = await channel_reader.force_parse_channel(
        channel_id=channel_id,
        channel_username=channel.get("username"),
        limit=limit,
        days=days,
    )
    return {"stats": stats}


@app.post("/api/sources/parse-all")
async def parse_all(limit: int = 100, days: int = 3):
    totals = {"parsed": 0, "skipped": 0, "errors": 0}
    details = []
    for channel in db.get_all_channels():
        stats = await channel_reader.force_parse_channel(
            channel_id=channel["channel_id"],
            channel_username=channel.get("username"),
            limit=limit,
            days=days,
        )
        for key in totals:
            totals[key] += stats.get(key, 0)
        details.append({"channel_id": channel["channel_id"], "title": channel.get("title"), "stats": stats})
    return {"totals": totals, "details": details}


@app.get("/api/news")
async def news(days: int = 1, limit: int = 100):
    end = datetime.now()
    start = end - timedelta(days=days)
    rows = db.get_news_by_period(start.isoformat(), end.isoformat())[:limit]
    return {"news": rows, "count": len(rows)}


@app.post("/api/news/summary")
async def summarize_news(payload: SummaryPayload):
    end = datetime.now()
    start = end - timedelta(days=payload.days)
    rows = db.get_news_by_period(start.isoformat(), end.isoformat())
    unique = await Deduplicator(_llm_client()).deduplicate(rows)
    summary = await _llm_client().aggregate_news(unique, f"{start.date()} - {end.date()}")
    return {"summary": summary, "input_count": len(rows), "unique_count": len(unique)}


# ---- Posting bots ---------------------------------------------------------


def _safe_bot(record: Dict[str, Any]) -> Dict[str, Any]:
    """Drop the raw token from a bot record before returning it to the UI."""
    out = {k: v for k, v in record.items() if k != "token"}
    out["token_masked"] = _mask_token(record.get("token") or "")
    return out


@app.get("/api/posting/bots")
async def list_posting_bots():
    return {"bots": [_safe_bot(item) for item in db.list_bots()]}


@app.post("/api/posting/bots")
async def create_posting_bot(payload: BotPayload):
    bot_id = db.create_bot(
        label=payload.label.strip(),
        kind=payload.kind,
        token=(payload.token or "").strip() or None,
        default_chat_id=(payload.default_chat_id or "").strip() or None,
        enabled=bool(payload.enabled),
    )
    return _safe_bot(db.get_bot(bot_id))


@app.patch("/api/posting/bots/{bot_id}")
async def update_posting_bot(bot_id: int, payload: BotUpdatePayload):
    updates = payload.model_dump(exclude_unset=True)
    if "token" in updates and updates["token"] is not None:
        updates["token"] = updates["token"].strip() or None
    if "default_chat_id" in updates and updates["default_chat_id"] is not None:
        updates["default_chat_id"] = updates["default_chat_id"].strip() or None
    if not db.update_bot(bot_id, **updates):
        raise HTTPException(status_code=404, detail="Bot not found")
    return _safe_bot(db.get_bot(bot_id))


@app.delete("/api/posting/bots/{bot_id}")
async def delete_posting_bot(bot_id: int):
    return {"removed": db.delete_bot(bot_id)}


# ---- LLM prompts ----------------------------------------------------------


@app.get("/api/prompts")
async def get_prompts(task: Optional[str] = None):
    if task and task not in {"dedup", "summary", "tags", "repost"}:
        raise HTTPException(status_code=400, detail="Unknown task")
    return {"prompts": db.list_prompts(task=task)}


@app.post("/api/prompts")
async def upsert_prompt(payload: PromptPayload):
    prompt_id = db.upsert_prompt(
        task=payload.task,
        name=payload.name.strip(),
        system_prompt=payload.system_prompt,
        user_template=payload.user_template,
        is_active=payload.is_active,
    )
    return {"id": prompt_id, "prompt": next(
        (p for p in db.list_prompts(task=payload.task) if p["id"] == prompt_id),
        None,
    )}


@app.post("/api/prompts/test")
async def test_prompt_endpoint(payload: PromptTestPayload):
    """Run a one-off chat request with the given prompt against current LLM.

    Used by the prompt editor to preview output without saving anything.
    Placeholders {news}, {period}, {instruction} are substituted in the
    user_template before sending.
    """
    sample = (payload.sample_news or "").strip()
    if not sample:
        # Fall back to the last 5 news items so the user gets a realistic
        # preview when they haven't typed any sample.
        end = datetime.now()
        start = end - timedelta(days=2)
        rows = db.get_news_by_period(start.isoformat(), end.isoformat())[:5]
        sample = "\n\n".join(
            f"{i+1}. [{row.get('title') or row.get('username') or 'src'}] {row.get('date','')}\n{row.get('text','')}"
            for i, row in enumerate(rows)
        ) or "1. [demo] Пример новости: OpenAI выпустила обновление модели."

    user_text = (
        payload.user_template
        .replace("{news}", sample)
        .replace("{period}", payload.period or "demo")
        .replace("{instruction}", payload.instruction or "")
    )
    try:
        text = await _llm_client().chat(payload.system_prompt, user_text)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"text": text or "", "sample_used": sample}


@app.post("/api/prompts/{prompt_id}/activate")
async def activate_prompt(prompt_id: int):
    if not db.set_active_prompt(prompt_id):
        raise HTTPException(status_code=404, detail="Prompt not found")
    return {"ok": True}


@app.delete("/api/prompts/{prompt_id}")
async def delete_prompt(prompt_id: int):
    return {"removed": db.delete_prompt(prompt_id)}


# ---- Posting --------------------------------------------------------------


def _collect_news_for_post(payload: PostingPreviewPayload) -> List[Dict[str, Any]]:
    if payload.news_ids:
        items: List[Dict[str, Any]] = []
        # Reuse the period query so we get joined channel info, then filter.
        end = datetime.now()
        start = end - timedelta(days=365 * 5)
        wanted = set(int(x) for x in payload.news_ids)
        for row in db.get_news_by_period(start.isoformat(), end.isoformat()):
            if row["id"] in wanted:
                items.append(row)
        return items
    days = payload.days or 1
    end = datetime.now()
    start = end - timedelta(days=days)
    return db.get_news_by_period(start.isoformat(), end.isoformat())


@app.post("/api/posting/preview")
async def posting_preview(payload: PostingPreviewPayload):
    rows = _collect_news_for_post(payload)
    if not rows:
        raise HTTPException(status_code=400, detail="No news to use for the post")
    unique = await Deduplicator(_llm_client()).deduplicate(rows)
    text = await _llm_client().rewrite_post(
        unique,
        instruction=payload.instruction,
        prompt_name=payload.prompt_name,
    )
    if not text:
        raise HTTPException(status_code=502, detail="LLM did not return any text")
    return {
        "text": text,
        "input_count": len(rows),
        "unique_count": len(unique),
    }


@app.post("/api/posting/send")
async def posting_send(payload: PostingSendPayload):
    bot = db.get_bot(payload.bot_id)
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")
    if not bot.get("enabled"):
        raise HTTPException(status_code=400, detail="Bot is disabled")

    chat_id = (payload.chat_id or bot.get("default_chat_id") or "").strip()
    if not chat_id:
        raise HTTPException(status_code=400, detail="Target chat id is required")

    try:
        if bot["kind"] == "bot_api":
            result = await poster.send_via_bot_api(
                token=bot.get("token") or "",
                chat_id=chat_id,
                text=payload.text,
                parse_mode=payload.parse_mode,
                disable_web_page_preview=payload.disable_web_page_preview,
            )
        else:
            result = await poster.send_via_telethon(
                telegram_account_service=telegram_account,
                chat_id=chat_id,
                text=payload.text,
                link_preview=not payload.disable_web_page_preview,
            )
    except poster.PostingError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {"sent": True, "result": result, "bot_id": bot["id"], "chat_id": chat_id}


# ---- Pipelines ------------------------------------------------------------


@app.get("/api/pipelines")
async def list_pipelines_endpoint():
    return {"pipelines": db.list_pipelines()}


@app.get("/api/pipelines/{pipeline_id}")
async def get_pipeline_endpoint(pipeline_id: int):
    pipeline = db.get_pipeline(pipeline_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    return pipeline


def _check_cron(value: Optional[str]) -> Optional[str]:
    if not value or not value.strip():
        return None
    error = validate_cron(value.strip())
    if error:
        raise HTTPException(status_code=400, detail=f"Bad cron: {error}")
    return value.strip()


@app.post("/api/pipelines")
async def create_pipeline_endpoint(payload: PipelinePayload):
    cron = _check_cron(payload.schedule_cron)
    pipeline_id = db.upsert_pipeline(
        pipeline_id=None,
        name=payload.name.strip(),
        group_name=payload.group_name.strip() or "default",
        enabled=payload.enabled,
        schedule_cron=cron,
        steps=[step.model_dump() for step in payload.steps],
    )
    return db.get_pipeline(pipeline_id)


@app.put("/api/pipelines/{pipeline_id}")
async def update_pipeline_endpoint(pipeline_id: int, payload: PipelinePayload):
    if not db.get_pipeline(pipeline_id):
        raise HTTPException(status_code=404, detail="Pipeline not found")
    cron = _check_cron(payload.schedule_cron)
    db.upsert_pipeline(
        pipeline_id=pipeline_id,
        name=payload.name.strip(),
        group_name=payload.group_name.strip() or "default",
        enabled=payload.enabled,
        schedule_cron=cron,
        steps=[step.model_dump() for step in payload.steps],
    )
    return db.get_pipeline(pipeline_id)


@app.delete("/api/pipelines/{pipeline_id}")
async def delete_pipeline_endpoint(pipeline_id: int):
    return {"removed": db.delete_pipeline(pipeline_id)}


@app.post("/api/pipelines/{pipeline_id}/run")
async def run_pipeline_endpoint(pipeline_id: int):
    try:
        result = await pipeline_executor.run_pipeline(
            db=db,
            channel_reader=channel_reader,
            telegram_account_service=telegram_account,
            pipeline_id=pipeline_id,
            trigger="manual",
        )
        return result
    except pipeline_executor.PipelineError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/runs")
async def list_runs_endpoint(pipeline_id: Optional[int] = None, limit: int = 100):
    runs = db.list_runs(pipeline_id=pipeline_id, limit=min(limit, 500))
    return {"runs": runs}


# ---- Pipeline templates ----------------------------------------------------

_PIPELINE_TEMPLATES = {
    "full_pipeline": {
        "name": "Полный конвейер",
        "steps": [
            {"type": "parse_sources", "params": {"source_group": "all", "days": 1, "limit": 200}},
            {"type": "filter", "params": {"min_text_length": 30, "keywords_exclude": []}},
            {"type": "dedup", "params": {}},
            {"type": "compose_post", "params": {"prompt_name": "default", "include_image": True, "instruction": ""}},
            {"type": "publish", "params": {"bot_id": 0, "include_image": True}},
        ],
    },
    "summary_only": {
        "name": "Только сводка",
        "steps": [
            {"type": "parse_sources", "params": {"source_group": "all", "days": 1, "limit": 200}},
            {"type": "dedup", "params": {}},
            {"type": "summary", "params": {"period_label": "сутки"}},
        ],
    },
    "repost_only": {
        "name": "Только репост (без парсинга)",
        "steps": [
            {"type": "filter", "params": {"days": 1, "min_text_length": 30}},
            {"type": "dedup", "params": {}},
            {"type": "compose_post", "params": {"prompt_name": "default", "include_image": True}},
            {"type": "publish", "params": {"bot_id": 0, "include_image": True}},
        ],
    },
    "parse_only": {
        "name": "Только парсинг",
        "steps": [
            {"type": "parse_sources", "params": {"source_group": "all", "days": 3, "limit": 500}},
        ],
    },
}


@app.get("/api/pipeline-templates")
async def list_pipeline_templates():
    return {
        "templates": [
            {"id": key, "name": tpl["name"], "step_count": len(tpl["steps"]), "steps": tpl["steps"]}
            for key, tpl in _PIPELINE_TEMPLATES.items()
        ]
    }


@app.post("/api/pipelines/from-template")
async def create_pipeline_from_template(payload: PipelineTemplatePayload):
    tpl = _PIPELINE_TEMPLATES.get(payload.template)
    if not tpl:
        raise HTTPException(status_code=400, detail="Unknown template")
    pipeline_id = db.upsert_pipeline(
        pipeline_id=None,
        name=(payload.name or tpl["name"]).strip(),
        group_name="templates",
        enabled=False,  # let the user wire bot_id before enabling
        schedule_cron=None,
        steps=tpl["steps"],
    )
    return db.get_pipeline(pipeline_id)


# ---- News media ------------------------------------------------------------


@app.get("/api/news/{news_id}/media")
async def news_media_endpoint(news_id: int):
    media = db.get_media_for_news([news_id]).get(news_id, [])
    return {"media": media}


@app.get("/api/runs/{run_id}")
async def get_run_endpoint(run_id: int):
    detail = db.get_run_detail(run_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Run not found")
    return detail


_DEFAULT_PROMPTS = [
    {
        "task": "dedup",
        "name": "default",
        "system_prompt": (
            "Ты помощник для удаления дубликатов IT-новостей. "
            "Найди уникальные сообщения и верни ТОЛЬКО JSON массив их номеров, "
            "например: [1, 3, 5]. Никакого другого текста."
        ),
        "user_template": (
            "Проанализируй список новостей и верни JSON массив номеров уникальных:\n\n"
            "{news}\n\nОтвет — только JSON массив."
        ),
    },
    {
        "task": "summary",
        "name": "default",
        "system_prompt": (
            "Ты редактор IT-новостей. Делай краткую структурированную сводку: "
            "группируй похожие события, убирай повторы, сохраняй факты и источники. "
            "Пиши на русском, без рекламы."
        ),
        "user_template": (
            "Сделай сводку новостей за период {period}:\n\n{news}\n\n"
            "Формат:\n1. Короткий заголовок\n2. 1-3 предложения с сутью\n"
            "3. Источники в скобках, если есть."
        ),
    },
    {
        "task": "tags",
        "name": "default",
        "system_prompt": (
            "Ты помощник для генерации тегов. Верни только JSON массив из 3-5 "
            "коротких тегов на русском."
        ),
        "user_template": "Проанализируй новость и сгенерируй теги:\n\n{news}",
    },
    {
        "task": "repost",
        "name": "default",
        "system_prompt": (
            "Ты редактор IT-канала в Telegram. Сделай из подборки один компактный пост: "
            "1-3 абзаца, фактично, без воды. Эмодзи в начале каждой темы. "
            "В конце отдельной строкой — источники через запятую."
        ),
        "user_template": (
            "Подборка новостей:\n\n{news}\n\n"
            "Дополнительная инструкция от редактора: {instruction}"
        ),
    },
    {
        "task": "repost",
        "name": "short_announce",
        "system_prompt": (
            "Ты пишешь сжатые анонсы для IT-канала. Один пост — одна главная мысль, "
            "до 500 знаков. Без эмодзи. Финальная строка — источник."
        ),
        "user_template": "Выбери самую важную новость и сделай короткий анонс:\n\n{news}",
    },
]


def _seed_default_prompts() -> None:
    """Insert default prompt variants on first run.

    Existing entries are left untouched; the active flag is only set when
    there is no active prompt for the task yet.
    """
    for entry in _DEFAULT_PROMPTS:
        existing = next(
            (p for p in db.list_prompts(task=entry["task"]) if p["name"] == entry["name"]),
            None,
        )
        if existing:
            continue
        active_now = db.get_active_prompt(entry["task"]) is None and entry["name"] == "default"
        db.upsert_prompt(
            task=entry["task"],
            name=entry["name"],
            system_prompt=entry["system_prompt"],
            user_template=entry["user_template"],
            is_active=active_now,
        )


@app.on_event("startup")
async def startup_event():
    _apply_log_level()
    _write_runtime_env()
    _seed_default_prompts()
    pipeline_scheduler.start()


@app.on_event("shutdown")
async def shutdown_event():
    await pipeline_scheduler.stop()
    await telegram_account.disconnect()
    if channel_reader.parser_manager is not None:
        await channel_reader.parser_manager.close_all()
