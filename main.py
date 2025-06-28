import multiprocessing as mp
from multiprocessing import Manager
import time
import argparse

from src.processes.websocket_proc import websocket_process
from src.processes.trader_proc import trader_process
from src.processes.api_proc import api_process
from src.processes.telegram_proc import telegram_process
from src.database.database import DBWriter
from src.utils.logger import get_logger
from config.strategy_config import SYMBOLS
from config.api_config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID

logger = get_logger(__name__)


def main(strategy_name: str = "scalping", use_telegram: bool = True) -> None:
    """엔트리 포인트 – 멀티프로세스 초기화 및 실행"""

    mp.freeze_support()
    mp.set_start_method("fork", force=True)

    manager: Manager = mp.Manager()

    # 종목별 틱 큐 생성
    tick_queues = {symbol: manager.Queue(maxsize=2000) for symbol in SYMBOLS}
    command_q = manager.Queue()
    notify_q = manager.Queue()
    db_q = manager.Queue()
    resp_q = manager.Queue()
    order_q = manager.Queue()

    shutdown_ev = manager.Event()

    logger.info("AutoCoin 시작: 전략=%s, 종목=%s", strategy_name, SYMBOLS)

    procs: list[mp.Process] = []
    
    # 종목별 웹소켓 프로세스 생성
    for symbol in SYMBOLS:
        proc = mp.Process(
            target=websocket_process, 
            args=(symbol, tick_queues[symbol], shutdown_ev), 
            daemon=True,
            name=f"WebSocket-{symbol}"
        )
        procs.append(proc)
    
    # 통합 틱 큐 (모든 종목의 데이터를 하나로 합침)
    unified_tick_q = manager.Queue(maxsize=5000)
    
    # 틱 데이터 통합 프로세스
    tick_merger_proc = mp.Process(
        target=_tick_merger_process,
        args=(tick_queues, unified_tick_q, shutdown_ev),
        daemon=True,
        name="TickMerger"
    )
    procs.append(tick_merger_proc)
    
    # 나머지 프로세스들
    procs.extend([
        mp.Process(
            target=trader_process, 
            args=(unified_tick_q, command_q, notify_q, db_q, order_q, resp_q, shutdown_ev, strategy_name), 
            daemon=True,
            name="Trader"
        ),
        mp.Process(
            target=api_process, 
            args=(order_q, resp_q, notify_q, shutdown_ev), 
            daemon=True,
            name="API"
        ),
    ])

    # Telegram 프로세스는 옵션
    optional_procs: list[mp.Process] = []
    if use_telegram and TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
        optional_procs.append(
            mp.Process(
                target=telegram_process,
                args=(command_q, notify_q, shutdown_ev),
                daemon=True,
                name="Telegram",
            )
        )
    else:
        logger.info("Telegram 비활성화 상태로 시작합니다 (use_telegram=%s, token=%s, chat_id=%s)", use_telegram, bool(TELEGRAM_TOKEN), bool(TELEGRAM_CHAT_ID))

    procs.extend([
        *optional_procs,
        mp.Process(
            target=DBWriter.run, 
            args=(db_q, shutdown_ev), 
            daemon=True,
            name="Database"
        ),
    ])

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


def _tick_merger_process(tick_queues: dict, unified_queue, shutdown_ev) -> None:
    """여러 종목의 틱 데이터를 하나의 큐로 통합"""
    logger.info("틱 통합 프로세스 시작")
    
    while not shutdown_ev.is_set():
        try:
            # 각 종목의 큐에서 데이터 수집
            for symbol, queue in tick_queues.items():
                try:
                    if not queue.empty():
                        tick_data = queue.get_nowait()
                        # 종목 정보 추가
                        tick_data["market"] = symbol
                        tick_data["code"] = symbol
                        unified_queue.put_nowait(tick_data)
                except Exception:
                    continue
            
            time.sleep(0.001)  # CPU 사용률 조절
            
        except Exception as exc:
            logger.error("틱 통합 오류: %s", exc)
            time.sleep(0.1)
    
    logger.info("틱 통합 프로세스 종료")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AutoCoin 자동매매 봇")
    parser.add_argument(
        "--strategy", 
        default="scalping",
        choices=["scalping", "ma_cross", "rsi", "advanced_scalping"],
        help="사용할 전략 선택"
    )
    
    parser.add_argument(
        "--no-telegram",
        action="store_true",
        help="텔레그램 연결 없이 실행"
    )
    
    args = parser.parse_args()
    main(args.strategy, use_telegram=not args.no_telegram) 