from __future__ import annotations

import time
from multiprocessing import Event, Queue

from src.utils.notification import TelegramBot
from src.utils.logger import get_logger

logger = get_logger(__name__)


# pylint: disable=invalid-name
def telegram_process(cmd_q: Queue, tg_q: Queue, shutdown_ev: Event):
    """별도 프로세스에서 telegram bot polling"""

    logger.info("Telegram 프로세스 시작")
    TelegramBot.run(command_q=cmd_q, notify_q=tg_q, stop_event=shutdown_ev)  # 재사용
    logger.info("Telegram 프로세스 종료") 