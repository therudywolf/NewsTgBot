"""Scheduler for periodic channel checking.

NewsTgBot - Self-hosted IT news aggregator
Copyright (C) 2026 therudywolf
Licensed under AGPL-3.0
"""
import asyncio
import logging
from typing import Callable
import config

logger = logging.getLogger(__name__)


class Scheduler:
    """Simple scheduler for periodic tasks."""
    
    def __init__(self, interval_seconds: int = None):
        """Initialize scheduler."""
        self.interval_seconds = interval_seconds
        self.running = False
        self.task = None
    
    async def _run_periodic(self, coro: Callable):
        """Run a coroutine periodically."""
        while self.running:
            try:
                await coro()
            except Exception as e:
                logger.error(f"Error in scheduled task: {e}", exc_info=True)
            interval = self.interval_seconds or config.get_check_interval()
            await asyncio.sleep(max(60, interval))
    
    def start(self, coro: Callable):
        """Start the scheduler."""
        if self.running:
            return
        
        self.running = True
        self.task = asyncio.create_task(self._run_periodic(coro))
    
    def stop(self):
        """Stop the scheduler."""
        self.running = False
        if self.task:
            self.task.cancel()
