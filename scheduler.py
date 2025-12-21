"""Scheduler for periodic channel checking."""
import asyncio
import logging
from typing import Callable
import config

logger = logging.getLogger(__name__)


class Scheduler:
    """Simple scheduler for periodic tasks."""
    
    def __init__(self, interval_seconds: int = None):
        """Initialize scheduler."""
        self.interval_seconds = interval_seconds or config.CHECK_INTERVAL_SECONDS
        self.running = False
        self.task = None
    
    async def _run_periodic(self, coro: Callable):
        """Run a coroutine periodically."""
        while self.running:
            try:
                await coro()
            except Exception as e:
                logger.error(f"Error in scheduled task: {e}", exc_info=True)
            await asyncio.sleep(self.interval_seconds)
    
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

