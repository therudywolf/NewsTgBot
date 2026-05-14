"""Pipeline step executor.

Each pipeline is a list of ordered steps. The executor walks them
sequentially, threading a mutable `context` dict between them and
recording per-step traces (input, output, error, duration) into the
DB so the UI can reconstruct what happened.

Step types implemented in stage B:
- parse_sources : run force_parse on a set of sources, collect news ids
- filter        : narrow news by keywords / length / date
- dedup         : LLM-based deduplication using the active 'dedup' prompt
- summary       : LLM summary using the active 'summary' prompt
- compose_post  : LLM rewrite using the active 'repost' prompt
- publish       : send context['post_text'] through a configured bot
- wait          : sleep for N seconds (handy for stage C scheduling)

NewsTgBot - Self-hosted IT news aggregator
Licensed under AGPL-3.0
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import config
import poster
from database import Database
from deduplicator import Deduplicator
from llm_client import LLMClient

logger = logging.getLogger(__name__)


STEP_TYPES = {
    "parse_sources",
    "filter",
    "dedup",
    "summary",
    "compose_post",
    "publish",
    "wait",
}


class PipelineError(RuntimeError):
    """Raised when a pipeline step cannot continue."""


def _llm_client() -> LLMClient:
    return LLMClient(
        api_url=config.get_lm_studio_base_url(),
        model_name=config.get_lm_studio_model(),
        api_token=config.get_lm_studio_api_token(),
        api_mode=config.get_lm_studio_api_mode(),
    )


async def _step_parse_sources(
    db: Database,
    channel_reader,
    params: Dict[str, Any],
    context: Dict[str, Any],
) -> Dict[str, Any]:
    source_ids: List[int] = params.get("source_ids") or []
    source_group: Optional[str] = params.get("source_group")
    limit = int(params.get("limit", 200))
    days = int(params.get("days", 7))

    all_channels = db.get_all_channels()
    if source_ids:
        wanted = [c for c in all_channels if c["channel_id"] in source_ids]
    elif source_group and source_group != "all":
        wanted = [c for c in all_channels if (c.get("source_type") or "telegram_bot") == source_group]
    else:
        wanted = all_channels

    parsed_total = 0
    skipped_total = 0
    errors_total = 0
    for ch in wanted:
        stats = await channel_reader.force_parse_channel(
            channel_id=ch["channel_id"],
            channel_username=ch.get("username"),
            limit=limit,
            days=days,
        )
        parsed_total += stats.get("parsed", 0)
        skipped_total += stats.get("skipped", 0)
        errors_total += stats.get("errors", 0)

    end = datetime.now()
    start = end - timedelta(days=days)
    news_ids = db.get_news_ids_by_period(start.isoformat(), end.isoformat())
    context["news_ids"] = news_ids
    context["last_parse_stats"] = {
        "parsed": parsed_total,
        "skipped": skipped_total,
        "errors": errors_total,
    }
    return {
        "sources_scanned": len(wanted),
        "news_ids_count": len(news_ids),
        "parsed": parsed_total,
        "skipped": skipped_total,
        "errors": errors_total,
    }


async def _step_filter(db: Database, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    ids: List[int] = context.get("news_ids") or []
    if not ids:
        days = int(params.get("days", 1))
        end = datetime.now()
        start = end - timedelta(days=days)
        ids = db.get_news_ids_by_period(start.isoformat(), end.isoformat())

    rows = db.get_news_by_ids(ids)
    include = [w.lower() for w in (params.get("keywords_include") or [])]
    exclude = [w.lower() for w in (params.get("keywords_exclude") or [])]
    min_length = int(params.get("min_text_length", 0))

    kept = []
    for row in rows:
        text = (row.get("text") or "")
        text_l = text.lower()
        if min_length and len(text) < min_length:
            continue
        if include and not any(w in text_l for w in include):
            continue
        if exclude and any(w in text_l for w in exclude):
            continue
        kept.append(row["id"])

    context["news_ids"] = kept
    return {"before": len(rows), "after": len(kept)}


async def _step_dedup(db: Database, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    ids: List[int] = context.get("news_ids") or []
    if not ids:
        days = int(params.get("days", 1))
        end = datetime.now()
        start = end - timedelta(days=days)
        ids = db.get_news_ids_by_period(start.isoformat(), end.isoformat())

    rows = db.get_news_by_ids(ids)
    if not rows:
        context["news_ids"] = []
        return {"before": 0, "after": 0}

    unique = await Deduplicator(_llm_client()).deduplicate(rows)
    unique_ids = [u["id"] for u in unique]
    context["news_ids"] = unique_ids
    return {"before": len(rows), "after": len(unique_ids)}


async def _step_summary(db: Database, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    ids: List[int] = context.get("news_ids") or []
    if not ids:
        raise PipelineError("summary step has no news ids in context")
    rows = db.get_news_by_ids(ids)
    period_label = params.get("period_label") or ""
    text = await _llm_client().aggregate_news(rows, period_label)
    context["summary_text"] = text
    return {"input_count": len(rows), "summary_length": len(text or "")}


async def _step_compose_post(db: Database, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    ids: List[int] = context.get("news_ids") or []
    if not ids:
        raise PipelineError("compose_post step has no news ids in context")
    rows = db.get_news_by_ids(ids)

    text = await _llm_client().rewrite_post(
        rows,
        instruction=params.get("instruction"),
        prompt_name=params.get("prompt_name"),
    )
    if not text:
        raise PipelineError("LLM returned empty post text")
    context["post_text"] = text.strip()

    image_url = None
    if params.get("include_image"):
        media = db.get_media_for_news(ids)
        for nid in ids:
            for item in media.get(nid, []):
                if item.get("kind") == "image" and item.get("url"):
                    image_url = item["url"]
                    break
            if image_url:
                break
        context["image_url"] = image_url

    return {
        "input_count": len(rows),
        "post_length": len(context["post_text"]),
        "image_url": image_url,
    }


async def _step_publish(
    db: Database,
    telegram_account_service,
    params: Dict[str, Any],
    context: Dict[str, Any],
) -> Dict[str, Any]:
    bot_id = int(params.get("bot_id") or 0)
    if not bot_id:
        raise PipelineError("publish step requires bot_id")
    bot = db.get_bot(bot_id)
    if not bot:
        raise PipelineError(f"bot {bot_id} not found")
    if not bot.get("enabled"):
        raise PipelineError(f"bot {bot_id} is disabled")

    chat_id = (params.get("chat_id") or bot.get("default_chat_id") or "").strip()
    if not chat_id:
        raise PipelineError("publish step requires a chat id")

    text = (context.get("post_text") or params.get("text") or context.get("summary_text") or "").strip()
    if not text:
        raise PipelineError("publish step has no text to send")

    image_url = context.get("image_url") if params.get("include_image") else None
    parse_mode = params.get("parse_mode")

    try:
        if bot["kind"] == "bot_api":
            if image_url:
                result = await poster.send_photo_via_bot_api(
                    token=bot["token"] or "",
                    chat_id=chat_id,
                    photo_url=image_url,
                    caption=text,
                    parse_mode=parse_mode,
                )
            else:
                result = await poster.send_via_bot_api(
                    token=bot["token"] or "",
                    chat_id=chat_id,
                    text=text,
                    parse_mode=parse_mode,
                )
        else:
            result = await poster.send_via_telethon(
                telegram_account_service=telegram_account_service,
                chat_id=chat_id,
                text=text,
                link_preview=False,
            )
    except poster.PostingError as exc:
        raise PipelineError(str(exc)) from exc

    return {"chat_id": chat_id, "bot_id": bot_id, "result": result}


async def _step_wait(params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    seconds = float(params.get("seconds", 0))
    seconds = max(0.0, min(seconds, 600.0))
    await asyncio.sleep(seconds)
    return {"slept": seconds}


async def run_pipeline(
    db: Database,
    channel_reader,
    telegram_account_service,
    pipeline_id: int,
    trigger: str = "manual",
) -> Dict[str, Any]:
    """Execute a stored pipeline and return its final run record."""
    pipeline = db.get_pipeline(pipeline_id)
    if not pipeline:
        raise PipelineError(f"pipeline {pipeline_id} not found")
    if not pipeline.get("enabled") and trigger != "manual":
        raise PipelineError("pipeline is disabled")

    run_id = db.create_run(pipeline_id, trigger=trigger)
    logger.info("Pipeline %s run #%s started (trigger=%s)", pipeline["name"], run_id, trigger)
    context: Dict[str, Any] = {}
    final_status = "success"
    final_error: Optional[str] = None

    for step in pipeline.get("steps") or []:
        step_started = datetime.now().isoformat()
        step_type = step["type"]
        params = step.get("params") or {}
        if step_type not in STEP_TYPES:
            db.add_step_run(run_id, step.get("id"), step["position"], step_type, "failed",
                            step_started, datetime.now().isoformat(),
                            input_data={"context_keys": list(context.keys())},
                            output_data=None,
                            error=f"unknown step type {step_type}")
            final_status = "failed"
            final_error = f"unknown step type {step_type}"
            break

        try:
            if step_type == "parse_sources":
                output = await _step_parse_sources(db, channel_reader, params, context)
            elif step_type == "filter":
                output = await _step_filter(db, params, context)
            elif step_type == "dedup":
                output = await _step_dedup(db, params, context)
            elif step_type == "summary":
                output = await _step_summary(db, params, context)
            elif step_type == "compose_post":
                output = await _step_compose_post(db, params, context)
            elif step_type == "publish":
                output = await _step_publish(db, telegram_account_service, params, context)
            elif step_type == "wait":
                output = await _step_wait(params, context)
            else:  # pragma: no cover — defensive
                raise PipelineError(f"unhandled step type {step_type}")

            db.add_step_run(
                run_id,
                step.get("id"),
                step["position"],
                step_type,
                "success",
                step_started,
                datetime.now().isoformat(),
                input_data={"params": params, "news_ids_count": len(context.get("news_ids") or [])},
                output_data=output,
                error=None,
            )
        except Exception as exc:  # noqa: BLE001 — record the failure and stop
            logger.exception("Pipeline %s step #%s (%s) failed", pipeline["name"], step["position"], step_type)
            db.add_step_run(
                run_id,
                step.get("id"),
                step["position"],
                step_type,
                "failed",
                step_started,
                datetime.now().isoformat(),
                input_data={"params": params},
                output_data=None,
                error=str(exc),
            )
            final_status = "failed"
            final_error = f"step {step['position']} ({step_type}): {exc}"
            break

    summary_output = {
        "news_ids_count": len(context.get("news_ids") or []),
        "post_length": len(context.get("post_text") or ""),
        "has_summary": bool(context.get("summary_text")),
        "image_url": context.get("image_url"),
    }
    db.finish_run(run_id, final_status, output=summary_output, error=final_error)
    return {"run_id": run_id, "status": final_status, "error": final_error, "output": summary_output}
