from __future__ import annotations
import threading
import time
from queue import Queue
from typing import List, Optional
import pyupbit
from src.utils.logger import get_logger

logger = get_logger(__name__)


class WebSocketClient:
    """업비트 웹소켓으로부터 실시간 데이터 수신 (자동 재연결 지원)"""

    def __init__(self, channels: List[str], symbols: List[str]):
        self.channels = channels
        self.symbols = symbols
        self.wm: Optional[pyupbit.WebSocketManager] = None
        self.last_heartbeat = time.time()
        self.heartbeat_timeout = 30.0  # 30초 이상 데이터 없으면 재연결
        self.is_connected = False

    def connect(self) -> bool:
        """웹소켓 연결"""
        try:
            if self.wm:
                self.wm.close()
            
            # 채널별 WebSocketManager 생성
            if "ticker" in self.channels:
                self.wm = pyupbit.WebSocketManager("ticker", self.symbols)
            elif "orderbook" in self.channels:
                self.wm = pyupbit.WebSocketManager("orderbook", self.symbols)
            else:
                self.wm = pyupbit.WebSocketManager("ticker", self.symbols)
            
            self.last_heartbeat = time.time()
            self.is_connected = True
            logger.info("WebSocket 연결 성공: %s, %s", self.channels, self.symbols)
            return True
            
        except Exception as exc:
            logger.error("WebSocket 연결 실패: %s", exc)
            self.is_connected = False
            return False

    def disconnect(self) -> None:
        """웹소켓 연결 해제"""
        if self.wm:
            try:
                self.wm.close()
                logger.info("WebSocket 연결 해제")
            except Exception as exc:
                logger.warning("WebSocket 해제 중 오류: %s", exc)
            finally:
                self.wm = None
                self.is_connected = False

    def check_heartbeat(self) -> bool:
        """heartbeat 체크 - 일정 시간 이상 데이터가 없으면 False 반환"""
        return (time.time() - self.last_heartbeat) < self.heartbeat_timeout

    def get_data(self) -> Optional[dict]:
        """데이터 수신 (None이면 데이터 없음)"""
        if not self.wm or not self.is_connected:
            return None
            
        try:
            data = self.wm.get()
            if data is not None:
                self.last_heartbeat = time.time()
            return data
        except Exception as exc:
            logger.warning("데이터 수신 중 오류: %s", exc)
            self.is_connected = False
            return None

    def run_with_reconnect(self, market_queue: Queue, stop_event: threading.Event, 
                          max_retries: int = -1, backoff_base: float = 1.0, 
                          max_backoff: float = 32.0) -> None:
        """자동 재연결을 지원하는 메인 실행 루프"""
        
        retry_count = 0
        backoff = backoff_base
        
        while not stop_event.is_set():
            # 최대 재시도 횟수 체크
            if max_retries > 0 and retry_count >= max_retries:
                logger.error("최대 재시도 횟수 초과: %d", max_retries)
                break
            
            # 연결 시도
            if not self.is_connected:
                if not self.connect():
                    retry_count += 1
                    logger.warning("재연결 실패 (%d/%s), %s초 후 재시도", 
                                 retry_count, max_retries if max_retries > 0 else "∞", backoff)
                    time.sleep(backoff)
                    backoff = min(backoff * 2, max_backoff)
                    continue
                else:
                    # 연결 성공 시 백오프 리셋
                    retry_count = 0
                    backoff = backoff_base
            
            # 데이터 수신 및 처리
            try:
                data = self.get_data()
                
                if data is None:
                    # heartbeat 체크
                    if not self.check_heartbeat():
                        logger.warning("Heartbeat 타임아웃 - 재연결 필요")
                        self.is_connected = False
                        continue
                    
                    # 짧은 대기 후 다시 시도
                    time.sleep(0.01)
                    continue
                
                # 큐에 데이터 추가
                try:
                    market_queue.put_nowait(data)
                except Exception:
                    # 큐가 가득 차면 가장 오래된 데이터를 버린다
                    if not market_queue.empty():
                        try:
                            market_queue.get_nowait()
                            market_queue.put_nowait(data)
                        except Exception as exc:
                            logger.warning("큐 처리 중 오류: %s", exc)
                            
            except KeyboardInterrupt:
                logger.info("사용자 중단 요청")
                break
            except Exception as exc:
                logger.error("예상치 못한 오류: %s", exc)
                self.is_connected = False
                time.sleep(1.0)  # 짧은 대기 후 재연결 시도
        
        # 정리
        self.disconnect()
        logger.info("WebSocket 클라이언트 종료")

    @staticmethod
    def run(symbol: str, market_queue: Queue, stop_event: threading.Event) -> None:
        """기존 호환성을 위한 static 메서드"""
        client = WebSocketClient(["ticker"], [symbol])
        client.run_with_reconnect(market_queue, stop_event)

    # ------------------------------------------------------------------
    # Dynamic subscription helpers
    # ------------------------------------------------------------------

    def update_symbols(self, symbols: list[str]) -> None:
        """구독 심볼 리스트를 동적으로 교체한다.

        현재 pyupbit.WebSocketManager 는 subscribe/unsubscribe API 를 직접 제공하지 않으므로
        내부 연결을 재설정하는 방식으로 구현한다.
        호출 시 self.symbols 를 갱신하고 다음 루프에서 재연결하도록 is_connected 를 False 로 설정한다.
        """
        if set(symbols) == set(self.symbols):
            return  # 변경 없음

        logger.info("WebSocketClient symbols 업데이트: %s → %s", self.symbols, symbols)
        self.symbols = symbols
        # 다음 루프에서 재연결되도록 플래그 변경
        self.is_connected = False
        # 즉시 disconnect 해서 빠르게 반영
        self.disconnect() 