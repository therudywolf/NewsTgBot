"""Cron-based scheduler for pipeline auto-runs.

A lightweight alternative to APScheduler. One asyncio task wakes up at
each wall-clock minute boundary, checks enabled pipelines whose
`schedule_cron` matches the current minute, and dispatches them through
`pipeline_executor.run_pipeline`. Pipelines that are still running from
a previous tick are skipped to avoid overlap.

Supported cron syntax: classic 5 fields (minute, hour, day-of-month,
month, day-of-week) with `*`, `,` lists, `-` ranges and `/` steps.
Day-of-week accepts 0=Sun..6=Sat plus `7` as Sunday.

NewsTgBot - Self-hosted IT news aggregator
Licensed under AGPL-3.0
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, Set

import pipeline_executor
from database import Database

logger = logging.getLogger(__name__)


def _expand_field(spec: str, low: int, high: int) -> Set[int]:
    spec = spec.strip()
    values: Set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        step = 1
        if "/" in part:
            base, step_str = part.split("/", 1)
            step = int(step_str)
        else:
            base = part
        if base == "*":
            start, end = low, high
        elif "-" in base:
            start_str, end_str = base.split("-", 1)
            start = int(start_str)
            end = int(end_str)
        else:
            start = end = int(base)
        if start < low or end > high or start > end or step <= 0:
            raise ValueError(f"cron field out of range: {spec!r}")
        values.update(range(start, end + 1, step))
    return values


class CronExpression:
    """Pre-parsed cron expression that answers `matches(when)`."""

    __slots__ = ("minutes", "hours", "days", "months", "dows", "raw")

    def __init__(self, raw: str):
        parts = raw.strip().split()
        if len(parts) != 5:
            raise ValueError(f"cron must have 5 fields, got {len(parts)}: {raw!r}")
        self.raw = raw
        self.minutes = _expand_field(parts[0], 0, 59)
        self.hours = _expand_field(parts[1], 0, 23)
        self.days = _expand_field(parts[2], 1, 31)
        self.months = _expand_field(parts[3], 1, 12)
        dows = _expand_field(parts[4], 0, 7)
        if 7 in dows:
            dows.discard(7)
            dows.add(0)
        self.dows = dows

    def matches(self, when: datetime) -> bool:
        if when.minute not in self.minutes:
            return False
        if when.hour not in self.hours:
            return False
        if when.month not in self.months:
            return False
        dom_full = self.days == set(range(1, 32))
        dow_full = self.dows == {0, 1, 2, 3, 4, 5, 6}
        # weekday(): Mon=0..Sun=6. Cron uses Sun=0..Sat=6.
        dow_value = (when.weekday() + 1) % 7
        if dom_full and dow_full:
            return True
        if dom_full:
            return dow_value in self.dows
        if dow_full:
            return when.day in self.days
        return when.day in self.days or dow_value in self.dows


def validate_cron(expression: str) -> Optional[str]:
    """Return None if *expression* parses, else a short human error."""
    try:
        CronExpression(expression)
    except ValueError as exc:
        return str(exc)
    return None


class PipelineScheduler:
    """Background asyncio task that fires due pipelines every minute."""

    def __init__(self, db: Database, channel_reader, telegram_account_service):
        self.db = db
        self.channel_reader = channel_reader
        self.telegram_account_service = telegram_account_service
        self._task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()
        self._last_check_minute: Optional[datetime] = None
        self._running_pipelines: Set[int] = set()

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._loop(), name="pipeline-scheduler")
        logger.info("Pipeline scheduler started")

    async def stop(self) -> None:
        if not self._task:
            return
        self._stop.set()
        try:
            await asyncio.wait_for(self._task, timeout=5)
        except asyncio.TimeoutError:
            self._task.cancel()
        self._task = None
        logger.info("Pipeline scheduler stopped")

    async def _loop(self) -> None:
        try:
            while not self._stop.is_set():
                await self._sleep_to_next_minute()
                if self._stop.is_set():
                    break
                now = datetime.now().replace(second=0, microsecond=0)
                if self._last_check_minute == now:
                    continue
                self._last_check_minute = now
                try:
                    await self._tick(now)
                except Exception:
                    logger.exception("Scheduler tick failed")
        except asyncio.CancelledError:
            return

    async def _sleep_to_next_minute(self) -> None:
        now = datetime.now()
        next_minute = (now + timedelta(seconds=60 - now.second)).replace(microsecond=0)
        delay = max(1.0, (next_minute - now).total_seconds())
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=delay)
        except asyncio.TimeoutError:
            pass

    async def _tick(self, now: datetime) -> None:
        pipelines = self.db.list_pipelines()
        for pipeline in pipelines:
            if not pipeline.get("enabled"):
                continue
            cron = (pipeline.get("schedule_cron") or "").strip()
            if not cron:
                continue
            try:
                expr = CronExpression(cron)
            except ValueError as exc:
                logger.warning("Pipeline %s has invalid cron %r: %s", pipeline["id"], cron, exc)
                continue
            if not expr.matches(now):
                continue
            if pipeline["id"] in self._running_pipelines:
                logger.info("Pipeline %s skipped — previous run still in progress", pipeline["id"])
                continue
            asyncio.create_task(self._run_pipeline(pipeline["id"]))

    async def _run_pipeline(self, pipeline_id: int) -> None:
        self._running_pipelines.add(pipeline_id)
        try:
            await pipeline_executor.run_pipeline(
                db=self.db,
                channel_reader=self.channel_reader,
                telegram_account_service=self.telegram_account_service,
                pipeline_id=pipeline_id,
                trigger="schedule",
            )
        except pipeline_executor.PipelineError as exc:
            logger.warning("Scheduled pipeline %s failed: %s", pipeline_id, exc)
        except Exception:
            logger.exception("Scheduled pipeline %s crashed", pipeline_id)
        finally:
            self._running_pipelines.discard(pipeline_id)
