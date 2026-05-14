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
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from starlette.middleware.sessions import SessionMiddleware

import config
from auth import ensure_session_secret, hash_password, is_admin_configured, verify_password
from channel_reader import ChannelReader
from database import Database
from deduplicator import Deduplicator
from llm_client import LLMClient
from source_identity import stable_source_id
from telegram_account import TelegramAccountService

logger = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).resolve().parent
STATIC_DIR = ROOT_DIR / "web"

db = Database()
channel_reader = ChannelReader(db)
telegram_account = TelegramAccountService()

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

    if path.startswith("/static/") or path in PUBLIC_PATHS:
        return await call_next(request)

    if path.startswith("/api/") and not is_admin_configured(db):
        return JSONResponse(
            {"detail": "Admin setup required"},
            status_code=status.HTTP_409_CONFLICT,
        )

    if path.startswith("/api/") and not _is_authenticated(request):
        return JSONResponse(
            {"detail": "Authentication required"},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    return await call_next(request)


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
    if payload.username.strip() != username or not verify_password(payload.password, password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    request.session["authenticated"] = True
    request.session["username"] = username
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


@app.on_event("startup")
async def startup_event():
    _apply_log_level()
    _write_runtime_env()


@app.on_event("shutdown")
async def shutdown_event():
    await telegram_account.disconnect()
    if channel_reader.parser_manager is not None:
        await channel_reader.parser_manager.close_all()
