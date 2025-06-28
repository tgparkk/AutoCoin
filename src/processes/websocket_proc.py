from __future__ import annotations

import time
from multiprocessing import Event, Queue

from src.api.websocket import WebSocketClient
from src.utils.logger import get_logger
from config.settings import (
    WEBSOCKET_CHANNELS, 
    WEBSOCKET_MAX_RETRIES, 
    WEBSOCKET_BACKOFF_BASE, 
    WEBSOCKET_MAX_BACKOFF
)

logger = get_logger(__name__)


def websocket_process(symbol: str, tick_q: Queue, shutdown_ev: Event) -> None:  # pragma: no cover
    """실시간 틱 데이터를 tick_q로 보내는 별도 프로세스.

    설정에서 지정한 채널(ticker/orderbook)을 구독하고,
    오류 발생 시 지수(back-off)로 재연결한다.
    """
    
    logger.info("WebSocket 프로세스 시작: %s, 채널: %s", symbol, WEBSOCKET_CHANNELS)
    
    # WebSocket 클라이언트 생성
    client = WebSocketClient(WEBSOCKET_CHANNELS, [symbol])
    
    # 자동 재연결로 실행
    client.run_with_reconnect(
        market_queue=tick_q,
        stop_event=shutdown_ev,
        max_retries=WEBSOCKET_MAX_RETRIES,
        backoff_base=WEBSOCKET_BACKOFF_BASE,
        max_backoff=WEBSOCKET_MAX_BACKOFF
    )
    
    logger.info("WebSocket 프로세스 종료") 