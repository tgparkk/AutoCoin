import argparse
import multiprocessing as mp
import time
from multiprocessing import Manager

from src.processes.websocket_proc import websocket_process
from src.processes.trader_proc import trader_process
from src.processes.api_proc import api_process
from src.processes.telegram_proc import telegram_process
from src.database.database import DBWriter
from src.utils.logger import get_logger
from config.strategy_config import SYMBOLS
from config.api_config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
from src.utils.symbol_manager import SymbolManager
from src.indicators.indicator_worker import indicator_worker_process

logger = get_logger(__name__)


def main(strategy_name: str = "scalping", use_telegram: bool = True) -> None:
    """엔트리 포인트 – 멀티프로세스 초기화 및 실행"""

    # Docker 환경에서 안전한 멀티프로세싱을 위해 spawn 사용
    if mp.get_start_method(allow_none=True) != 'spawn':
        mp.set_start_method("spawn", force=True)

    manager: Manager = mp.Manager()

    # tick_queues 를 Manager.dict 로 만들어 동적 추가·삭제 가능하게
    tick_queues: dict = manager.dict()
    for symbol in SYMBOLS:
        tick_queues[symbol] = manager.Queue(maxsize=2000)

    # IndicatorWorker 공유 객체 -----------------------------------------
    buyable_symbols = manager.dict()  # {market: True}

    # 심볼 매니저 초기화 (메인 프로세스 전역) – buyable_symbols 활용
    symbol_manager = SymbolManager(SYMBOLS, buyable_symbols=buyable_symbols)

    # 심볼 업데이트 브로드캐스트용 큐 & Event
    symbols_event_q = manager.Queue()
    symbols_updated_ev = manager.Event()

    # WebSocket 프로세스 단일 인스턴스 관리 (재시작 대신 subscribe 업데이트 사용)
    ws_proc: mp.Process | None = None

    def _spawn_ws(symbols: list[str]):
        nonlocal ws_proc
        # 기존 프로세스가 있으면 종료 (초기 1회만 실행됨)
        if ws_proc is not None and ws_proc.is_alive():
            return

        # 큐 준비
        for sym in symbols:
            if sym not in tick_queues:
                tick_queues[sym] = manager.Queue(maxsize=2000)

        ws_proc = mp.Process(
            target=websocket_process,
            args=(symbols, tick_queues, shutdown_ev, symbols_event_q, symbols_updated_ev),
            daemon=False,  # pyupbit 내부에서 프로세스를 생성하므로 daemon=False 필요
            name="WebSocket"
        )
        ws_proc.start()
        procs.append(ws_proc)
        logger.info("웹소켓 프로세스 시작: %s (pid=%s)", symbols, ws_proc.pid)

    def _restart_ws(symbols: list[str]):
        nonlocal ws_proc
        if ws_proc and ws_proc.is_alive():
            ws_proc.terminate()
            ws_proc.join(timeout=3)
            logger.info("웹소켓 프로세스 재시작")
            if ws_proc in procs:
                procs.remove(ws_proc)
        _spawn_ws(symbols)

    command_q = manager.Queue()
    notify_q = manager.Queue()
    db_q = manager.Queue()
    resp_q = manager.Queue()
    order_q = manager.Queue()

    shutdown_ev = manager.Event()

    logger.info("AutoCoin 시작: 전략=%s, 종목=%s", strategy_name, SYMBOLS)

    procs: list[mp.Process] = []
    
    # 초기 웹소켓 프로세스 생성
    _spawn_ws(symbol_manager.symbols)
    
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
    trader_proc = mp.Process(
        target=trader_process, 
        args=(unified_tick_q, command_q, notify_q, db_q, order_q, resp_q, shutdown_ev, strategy_name), 
        daemon=True,
        name="Trader"
    )
    
    api_proc = mp.Process(
        target=api_process, 
        args=(order_q, resp_q, notify_q, shutdown_ev), 
        daemon=True,
        name="API"
    )
    
    db_proc = mp.Process(
        target=DBWriter.run, 
        args=(db_q, shutdown_ev), 
        daemon=True,
        name="Database"
    )
    
    procs.extend([trader_proc, api_proc, db_proc])

    # Telegram 프로세스는 옵션
    if use_telegram and TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
        telegram_proc = mp.Process(
            target=telegram_process,
            args=(command_q, notify_q, shutdown_ev),
            daemon=True,
            name="Telegram",
        )
        procs.append(telegram_proc)
    else:
        logger.info("Telegram 비활성화 상태로 시작합니다 (use_telegram=%s, token=%s, chat_id=%s)", use_telegram, bool(TELEGRAM_TOKEN), bool(TELEGRAM_CHAT_ID))

    # ---------------- IndicatorWorker 프로세스 -------------------------
    indicator_proc = mp.Process(
        target=indicator_worker_process,
        args=(unified_tick_q, buyable_symbols, shutdown_ev),
        daemon=True,
        name="IndicatorWorker",
    )
    procs.append(indicator_proc)

    # 프로세스 시작
    for p in procs:
        if not p.is_alive():  # 중복 시작 방지
            p.start()
            logger.info("프로세스 시작: %s (pid=%s)", p.name, p.pid)

    try:
        while any(p.is_alive() for p in procs):
            # 심볼 동적 갱신 체크 (30초 간격)
            try:
                if symbol_manager.maybe_refresh():
                    new_syms = symbol_manager.symbols
                    current_syms = set(tick_queues.keys())
                    add_syms = set(new_syms) - current_syms
                    rem_syms = current_syms - set(new_syms)

                    if add_syms or rem_syms:
                        # 큐 생성/제거
                        for s in add_syms:
                            tick_queues[s] = manager.Queue(maxsize=2000)
                        for s in rem_syms:
                            tick_queues.pop(s, None)

                        _spawn_ws(new_syms)

                        # WebSocket 프로세스에 심볼 업데이트 브로드캐스트
                        symbols_event_q.put(list(new_syms))
                        symbols_updated_ev.set()

            except Exception as exc:  # pragma: no cover
                logger.warning("Symbol refresh error: %s", exc)

            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt 감지 – 종료 신호 발송")
        shutdown_ev.set()
    finally:
        # 모든 프로세스 종료 대기
        for p in procs:
            if p.is_alive():
                p.terminate()
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