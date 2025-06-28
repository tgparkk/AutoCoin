import multiprocessing as mp
from multiprocessing import Manager
import time

from src.processes.websocket_proc import websocket_process
from src.processes.trader_proc import trader_process
from src.processes.api_proc import api_process
from src.processes.telegram_proc import telegram_process
from src.database.database import DBWriter
from src.utils.logger import get_logger

logger = get_logger(__name__)


def main() -> None:  # noqa: D401
    """엔트리 포인트 – 멀티프로세스 초기화 및 실행"""

    mp.freeze_support()
    mp.set_start_method("fork", force=True)

    manager: Manager = mp.Manager()

    tick_q = manager.Queue(maxsize=2000)
    command_q = manager.Queue()
    notify_q = manager.Queue()
    db_q = manager.Queue()
    resp_q = manager.Queue()
    order_q = manager.Queue()

    shutdown_ev = manager.Event()

    symbol = "KRW-BTC"  # TODO: 설정 파일로 분리

    procs: list[mp.Process] = [
        mp.Process(target=websocket_process, args=(symbol, tick_q, shutdown_ev), daemon=True),
        mp.Process(target=trader_process, args=(tick_q, command_q, notify_q, db_q, order_q, resp_q, shutdown_ev), daemon=True),
        mp.Process(target=api_process, args=(order_q, resp_q, notify_q, shutdown_ev), daemon=True),
        mp.Process(target=telegram_process, args=(command_q, notify_q, shutdown_ev), daemon=True),
        mp.Process(target=DBWriter.run, args=(db_q, shutdown_ev), daemon=True),
    ]

    for p in procs:
        p.start()
        logger.info("프로세스 시작: %s (pid=%s)", p.name, p.pid)

    try:
        while any(p.is_alive() for p in procs):
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt 감지 – 종료 신호 발송")
        shutdown_ev.set()
    finally:
        for p in procs:
            p.join(timeout=5)
            logger.info("프로세스 종료: %s", p.name)


if __name__ == "__main__":
    main() 