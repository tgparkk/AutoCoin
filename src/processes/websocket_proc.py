from __future__ import annotations

import time
from multiprocessing import Event, Queue
from typing import List, Dict
import threading

from queue import Empty

from src.api.websocket import WebSocketClient
from src.utils.logger import get_logger
from config.settings import (
    WEBSOCKET_CHANNELS, 
    WEBSOCKET_MAX_RETRIES, 
    WEBSOCKET_BACKOFF_BASE, 
    WEBSOCKET_MAX_BACKOFF
)

logger = get_logger(__name__)


def websocket_process(
    symbols: List[str],
    tick_queues: Dict[str, Queue],
    shutdown_ev: Event,
    symbols_event_q: Queue,
    symbols_updated_ev: Event,
) -> None:  # pragma: no cover
    """다중 심볼을 한 세션으로 구독하여 개별 tick_queues 로 분배하고, 실시간 심볼 변경을 처리한다."""

    logger.info("WebSocket 프로세스 시작 – symbols=%s, 채널=%s", symbols, WEBSOCKET_CHANNELS)

    ws_queue: Queue = Queue(maxsize=5000)

    # 클라이언트 레퍼런스 저장용
    clients: Dict[str, WebSocketClient] = {}

    # ---------------- WebSocket 클라이언트 스레드 ----------------
    def _client_thread(channel: str):
        """채널별(WebSocketManager 타입별) 독립 실행"""
        client = WebSocketClient([channel], symbols)
        clients[channel] = client  # 외부 업데이트용 참조 저장
        client.run_with_reconnect(
            market_queue=ws_queue,
            stop_event=shutdown_ev,
            max_retries=WEBSOCKET_MAX_RETRIES,
            backoff_base=WEBSOCKET_BACKOFF_BASE,
            max_backoff=WEBSOCKET_MAX_BACKOFF,
        )

    # ticker/orderbook 각 채널에 대해 스레드 생성
    threads: list[threading.Thread] = []
    for ch in WEBSOCKET_CHANNELS:
        th = threading.Thread(target=_client_thread, args=(ch,), daemon=True, name=f"WS-{ch}")
        th.start()
        threads.append(th)

    # ---------------- symbols_updated listener ----------------
    current_symbols = set(symbols)

    def _listener():
        """Event + Queue 조합으로 심볼 변경을 수신하고 클라이언트에 반영"""
        nonlocal current_symbols
        from queue import Empty as _Empty  # 지역 import로 의존 최소화

        while not shutdown_ev.is_set():
            # Event 대기 – 설정되지 않으면 0.5초마다 확인
            if not symbols_updated_ev.wait(timeout=0.5):
                continue

            # 다른 리스너들을 위해 바로 클리어
            symbols_updated_ev.clear()

            # 큐에 누적된 최신 심볼 목록을 모두 소비하되 마지막 값만 사용
            latest_syms: List[str] | None = None
            while True:
                try:
                    latest_syms = symbols_event_q.get_nowait()
                except _Empty:
                    break
                except Exception:
                    break

            if latest_syms is None:
                continue

            new_set = set(latest_syms)
            if new_set == current_symbols:
                continue

            logger.info("[WebSocket] 심볼 업데이트 수신: %s → %s", list(current_symbols), latest_syms)
            current_symbols = new_set

            # 클라이언트별 업데이트
            for cl in clients.values():
                try:
                    cl.update_symbols(list(current_symbols))
                except Exception as exc:  # pragma: no cover
                    logger.warning("Client update_symbols error: %s", exc)

    listener_th = threading.Thread(target=_listener, daemon=True, name="WS-SymbolListener")
    listener_th.start()

    while not shutdown_ev.is_set():
        try:
            data = ws_queue.get(timeout=0.5)
        except Empty:
            continue
        except Exception as exc:  # pragma: no cover
            logger.warning("ws_queue error: %s", exc)
            continue

        # data 는 dict 형태, market 혹은 code 필드에 심볼이 있음
        symbol = data.get("code") or data.get("market")
        if not symbol:
            continue

        # ---------------- ORDERBOOK 데이터 가공 ----------------
        if data.get("type") == "orderbook":
            units = data.get("orderbook_units", [])
            if units:
                best_bid = units[0].get("bid_price")
                best_ask = units[0].get("ask_price")
                if best_bid is not None and best_ask is not None:
                    data["best_bid"] = best_bid
                    data["best_ask"] = best_ask
                    data["spread"] = best_ask - best_bid
                    # BaseStrategy 에서 price 가 필요하므로 중간값을 trade_price 로 사용
                    data["trade_price"] = (best_bid + best_ask) / 2

        q = tick_queues.get(symbol)
        if q is None:
            # 새로운 심볼이면 무시
            continue

        _safe_put(q, data)

    logger.info("WebSocket 프로세스 종료")


# ---------------------------------------------------------------------------
# 내부 헬퍼
# ---------------------------------------------------------------------------


def _safe_put(q: Queue, item):
    """큐가 가득 찼을 때 가장 오래된 항목을 버리고 item을 넣는다."""
    try:
        q.put_nowait(item)
    except Exception:
        try:
            q.get_nowait()
            q.put_nowait(item)
        except Exception:
            pass 