from __future__ import annotations

import time
from multiprocessing import Event, Queue

from src.api.websocket import WebSocketClient
from src.utils.logger import get_logger

logger = get_logger(__name__)


def websocket_process(symbol: str, tick_q: Queue, shutdown_ev: Event) -> None:  # pragma: no cover
    """실시간 틱 데이터를 tick_q로 보내는 별도 프로세스.

    오류 발생 시 지수(back-off)로 재연결한다.
    """

    backoff = 1.0
    MAX_BACKOFF = 32.0

    while not shutdown_ev.is_set():
        logger.info("WebSocket 연결 시도: %s", symbol)
        try:
            WebSocketClient.run(symbol, tick_q, shutdown_ev)
            # run() 이 정상 종료될 경우 (stop_event 세트) 루프 탈출
            if shutdown_ev.is_set():
                break
        except Exception as exc:  # pragma: no cover – 연결 실패
            logger.warning("WebSocket 오류: %s, %s초 후 재시도", exc, backoff)
            time.sleep(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF)

    logger.info("WebSocket 프로세스 종료") 