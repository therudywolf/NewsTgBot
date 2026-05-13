"""FastAPI admin panel for NewsTgBot.

NewsTgBot - Self-hosted IT news aggregator
Copyright (C) 2026 therudywolf

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published
by the Free Software Foundation, either version 3 of the License.
See LICENSE file for details.
"""
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import config
from channel_reader import ChannelReader
from database import Database
from deduplicator import Deduplicator
from llm_client import LLMClient
from source_identity import stable_source_id
from telegram_account import TelegramAccountService

logger = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).resolve().parent
STATIC_DIR = ROOT_DIR / "web"

app = FastAPI(title="NewsTgBot Admin", version="0.1.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

db = Database()
channel_reader = ChannelReader(db)
telegram_account = TelegramAccountService()


class SettingsPayload(BaseModel):
    lm_studio_base_url: Optional[str] = None
    lm_studio_model: Optional[str] = None
    lm_studio_api_mode: Optional[str] = Field(default=None, pattern="^(native|openai)$")


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


def _safe_config() -> Dict[str, Any]:
    settings = db.get_settings()
    base_url = settings.get("lm_studio_base_url") or config.LM_STUDIO_BASE_URL
    model = settings.get("lm_studio_model") or config.LM_STUDIO_MODEL
    api_mode = settings.get("lm_studio_api_mode") or config.LM_STUDIO_API_MODE
    bot_token = config.get_bot_token()

    return {
        "database_path": config.DATABASE_PATH,
        "channels_json_path": config.CHANNELS_JSON_PATH,
        "telegram_bot_configured": bool(bot_token),
        "telegram_bot_token_masked": _mask_token(bot_token),
        "telethon_configured": bool(config.get_telethon_api_id() and config.get_telethon_api_hash()),
        "telethon_phone": config.get_telethon_phone() or "",
        "lm_studio_base_url": base_url,
        "lm_studio_model": model,
        "lm_studio_api_mode": api_mode,
        "lm_studio_token_configured": bool(config.LM_STUDIO_API_TOKEN),
        "auto_parse_enabled": config.get_auto_parse_enabled(),
        "check_interval_seconds": config.get_check_interval(),
        "auto_parse_limit": config.get_auto_parse_limit(),
        "auto_parse_days": config.get_auto_parse_days(),
    }


def _llm_client() -> LLMClient:
    settings = db.get_settings()
    return LLMClient(
        api_url=settings.get("lm_studio_base_url") or config.LM_STUDIO_BASE_URL,
        model_name=settings.get("lm_studio_model") or config.LM_STUDIO_MODEL,
        api_mode=settings.get("lm_studio_api_mode") or config.LM_STUDIO_API_MODE,
    )


def _source_identifier(source: DefaultSourcePayload | ManualSourcePayload) -> str:
    if isinstance(source, DefaultSourcePayload):
        if source.source_type == "rss" and source.source_config.get("rss_url"):
            return source.source_config["rss_url"]
        return source.username
    return source.value


def _add_source(identifier: str, title: str, source_type: str, source_config: Dict[str, Any] = None) -> Dict[str, Any]:
    namespace = "rss" if source_type == "rss" else source_type
    channel_id = stable_source_id(identifier, namespace)
    username = identifier.strip()
    success = db.add_channel(channel_id, username, title, source_type=source_type)
    db.update_channel_source_type(channel_id, source_type, source_config or {})
    return {
        "created": success,
        "channel": db.get_channel_by_id(channel_id),
    }


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/status")
async def status():
    stats = db.get_global_stats()
    return {
        "ok": True,
        "time": datetime.now().isoformat(),
        "config": _safe_config(),
        "stats": stats,
    }


@app.get("/api/settings")
async def get_settings():
    return _safe_config()


@app.post("/api/settings")
async def update_settings(payload: SettingsPayload):
    if payload.lm_studio_base_url:
        db.set_setting("lm_studio_base_url", payload.lm_studio_base_url.rstrip("/"))
    if payload.lm_studio_model is not None:
        db.set_setting("lm_studio_model", payload.lm_studio_model)
    if payload.lm_studio_api_mode:
        db.set_setting("lm_studio_api_mode", payload.lm_studio_api_mode)
    return _safe_config()


@app.get("/api/bot-settings")
async def get_bot_settings():
    """Return bot configuration (tokens are masked)."""
    settings = db.get_settings()
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
    if payload.telegram_bot_token is not None:
        db.set_setting("telegram_bot_token", payload.telegram_bot_token.strip())
    if payload.auto_parse_enabled is not None:
        db.set_setting("auto_parse_enabled", payload.auto_parse_enabled)
    if payload.check_interval_seconds is not None:
        db.set_setting("check_interval_seconds", payload.check_interval_seconds)
    if payload.auto_parse_limit is not None:
        db.set_setting("auto_parse_limit", payload.auto_parse_limit)
    if payload.auto_parse_days is not None:
        db.set_setting("auto_parse_days", payload.auto_parse_days)
    if payload.telethon_api_id is not None:
        db.set_setting("telethon_api_id", payload.telethon_api_id.strip())
    if payload.telethon_api_hash is not None:
        db.set_setting("telethon_api_hash", payload.telethon_api_hash.strip())
    if payload.telethon_phone is not None:
        db.set_setting("telethon_phone", payload.telethon_phone.strip())
    return await get_bot_settings()


@app.get("/api/env-export")
async def export_env():
    """Generate .env file content from current settings for container restart."""
    settings = db.get_settings()
    bot_token = config.get_bot_token()
    lines = [
        f"TELEGRAM_BOT_TOKEN={bot_token}",
        "",
        f"TELETHON_API_ID={config.get_telethon_api_id()}",
        f"TELETHON_API_HASH={config.get_telethon_api_hash()}",
        f"TELETHON_PHONE={config.get_telethon_phone()}",
        f"TELETHON_SESSION_FILE={config.TELETHON_SESSION_FILE}",
        "",
        f"LM_STUDIO_BASE_URL={settings.get('lm_studio_base_url') or config.LM_STUDIO_BASE_URL}",
        f"LM_STUDIO_API_TOKEN={config.LM_STUDIO_API_TOKEN}",
        f"LM_STUDIO_MODEL={settings.get('lm_studio_model') or config.LM_STUDIO_MODEL}",
        f"LM_STUDIO_API_MODE={settings.get('lm_studio_api_mode') or config.LM_STUDIO_API_MODE}",
        f"LLM_TEMPERATURE={config.LLM_TEMPERATURE}",
        f"LLM_MAX_OUTPUT_TOKENS={config.LLM_MAX_OUTPUT_TOKENS}",
        f"LLM_CONTEXT_LENGTH={config.LLM_CONTEXT_LENGTH}",
        "",
        f"DATA_DIR={config.DATA_DIR}",
        f"LOGS_DIR={config.LOGS_DIR}",
        f"DATABASE_PATH={config.DATABASE_PATH}",
        f"CHANNELS_JSON_PATH={config.CHANNELS_JSON_PATH}",
        "",
        f"AUTO_PARSE_ENABLED={'true' if config.get_auto_parse_enabled() else 'false'}",
        f"CHECK_INTERVAL_SECONDS={config.get_check_interval()}",
        f"AUTO_PARSE_LIMIT={config.get_auto_parse_limit()}",
        f"AUTO_PARSE_DAYS={config.get_auto_parse_days()}",
        "",
        f'PARSER_PRIORITY={json.dumps(config.PARSER_PRIORITY)}',
        f"RSS_PARSER_TIMEOUT={config.RSS_PARSER_TIMEOUT}",
        f"WEB_PARSER_ENGINE={config.WEB_PARSER_ENGINE}",
        f"WEB_PARSER_HEADLESS={'true' if config.WEB_PARSER_HEADLESS else 'false'}",
        f"WEB_PARSER_TIMEOUT={config.WEB_PARSER_TIMEOUT}",
        "",
        f"LOG_LEVEL={logging.getLevelName(logging.getLogger().level)}",
    ]
    return {"content": "\n".join(lines)}


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
        return {"result": data, "settings": _safe_config()}
    except Exception as e:
        logger.error("LM Studio model load failed: %s", e)
        raise HTTPException(status_code=502, detail=str(e))


@app.post("/api/lm-studio/select")
async def lm_select_model(payload: LoadModelPayload):
    db.set_setting("lm_studio_model", payload.model)
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


@app.on_event("shutdown")
async def shutdown_event():
    await telegram_account.disconnect()
    await channel_reader.parser_manager.close_all()
