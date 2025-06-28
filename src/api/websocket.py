from __future__ import annotations
import threading
from queue import Queue
import pyupbit


class WebSocketClient:
    """업비트 웹소켓으로부터 실시간 데이터 수신"""

    @staticmethod
    def run(symbol: str, market_queue: Queue, stop_event: threading.Event) -> None:
        wm = pyupbit.WebSocketManager("ticker", [symbol])

        try:
            while not stop_event.is_set():
                data = wm.get()
                if data is None:
                    continue
                try:
                    market_queue.put_nowait(data)
                except Exception:
                    # 큐가 가득 차면 가장 오래된 데이터를 버린다.
                    if not market_queue.empty():
                        market_queue.get_nowait()
                        market_queue.put_nowait(data)
        except Exception as exc:
            print("WebSocket error:", exc)
        finally:
            wm.close() 