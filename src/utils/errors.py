from __future__ import annotations

class UpbitAPIError(Exception):
    """Upbit REST 호출 실패 시 발생하는 예외"""


class WebSocketReconnectError(Exception):
    """재연결 시도 최대 횟수를 초과했을 때 발생""" 