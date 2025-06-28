from __future__ import annotations
from queue import Queue, Empty
from threading import Event
from time import sleep

from telegram import Bot

from config.api_config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
from src.utils.logger import get_logger

logger = get_logger(__name__)


class TelegramBot:
    """텔레그램 알림 및 명령 처리"""

    POLL_INTERVAL = 2  # 초

    @staticmethod
    def run(command_q: Queue, notify_q: Queue, stop_event: Event) -> None:
        if TELEGRAM_TOKEN is None or TELEGRAM_CHAT_ID is None:
            logger.warning("텔레그램 토큰 또는 챗 ID 가 설정되지 않았습니다. TelegramThread 비활성화.")
            stop_event.wait()
            return

        bot = Bot(token=TELEGRAM_TOKEN)

        while not stop_event.is_set():
            # 알림 전송
            try:
                while True:
                    msg = notify_q.get_nowait()
                    bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=str(msg))
            except Empty:
                pass

            # TODO: 명령 수신 처리 (옵션)
            # 간단화를 위해 생략. 필요 시 python-telegram-bot Dispatcher 사용.

            sleep(TelegramBot.POLL_INTERVAL) 