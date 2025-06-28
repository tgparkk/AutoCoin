from __future__ import annotations
import pyupbit

from config.api_config import UPBIT_ACCESS_KEY, UPBIT_SECRET_KEY


class UpbitAPI:
    """pyupbit 래퍼 클래스"""

    def __init__(self) -> None:
        self._client = pyupbit.Upbit(UPBIT_ACCESS_KEY, UPBIT_SECRET_KEY)

    # ----------------------------- 계좌 ----------------------------- #
    def get_balance(self, ticker: str = "KRW") -> float:
        return self._client.get_balance(ticker)

    # ----------------------------- 주문 ----------------------------- #
    def buy_market(self, ticker: str, krw_amount: float):
        return self._client.buy_market_order(ticker, krw_amount)

    def sell_market(self, ticker: str, volume: float):
        return self._client.sell_market_order(ticker, volume) 