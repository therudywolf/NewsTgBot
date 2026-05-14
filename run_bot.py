"""Runtime wrapper for the Telegram bot worker."""

from __future__ import annotations

import logging
import time

import config
from bot import NewsBot, RestartRequested

logger = logging.getLogger(__name__)


def main():
    while True:
        token = config.get_bot_token()
        if not token:
            logger.info("Telegram bot token is not configured yet; waiting 10 seconds")
            time.sleep(10)
            continue

        try:
            NewsBot().run()
            return
        except RestartRequested as exc:
            logger.info("%s", exc)
            time.sleep(1)
        except Exception as exc:
            logger.error("Bot worker crashed: %s", exc, exc_info=True)
            time.sleep(5)


if __name__ == "__main__":
    main()
