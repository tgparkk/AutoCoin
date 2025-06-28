from threading import Thread, Event
from queue import Queue
import time

from src.api.websocket import WebSocketClient
from src.trading.trader import Trader
from src.utils.notification import TelegramBot
from src.database.database import DBWriter


def main() -> None:
    """엔트리 포인트 – 스레드 초기화 및 실행"""
    stop_event = Event()

    market_q: Queue = Queue(maxsize=2000)
    command_q: Queue = Queue()
    notify_q: Queue = Queue()
    db_q: Queue = Queue()

    threads = [
        Thread(target=WebSocketClient.run,
               args=("KRW-BTC", market_q, stop_event), daemon=True),
        Thread(target=Trader.run,
               args=(market_q, command_q, notify_q, db_q, stop_event), daemon=True),
        Thread(target=TelegramBot.run,
               args=(command_q, notify_q, stop_event), daemon=True),
        Thread(target=DBWriter.run,
               args=(db_q, stop_event), daemon=True),
    ]

    for t in threads:
        t.start()

    try:
        while not stop_event.is_set():
            time.sleep(1)
    except KeyboardInterrupt:
        stop_event.set()
        for t in threads:
            t.join()


if __name__ == "__main__":
    main() 