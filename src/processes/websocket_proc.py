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


def websocket_process(symbols: List[str], tick_queues: Dict[str, Queue], shutdown_ev: Event) -> None:  # pragma: no cover
    """다중 심볼을 한 세션으로 구독하여 개별 tick_queues 로 분배하는 프로세스"""

    logger.info("WebSocket 프로세스 시작 – symbols=%s, 채널=%s", symbols, WEBSOCKET_CHANNELS)

    ws_queue: Queue = Queue(maxsize=5000)

    # ---------------- WebSocket 클라이언트 스레드 ----------------
    def _client_thread(channel: str):
        """채널별(WebSocketManager 타입별) 독립 실행"""
        client = WebSocketClient([channel], symbols)
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