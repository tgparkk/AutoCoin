from __future__ import annotations
from collections import deque

from config.strategy_config import TAKE_PROFIT_PCT, STOP_LOSS_PCT
from .base_strategy import BaseStrategy


class ScalpingStrategy(BaseStrategy):
    """단순 가격 반전 기반 스캘핑 전략 예시"""

    def __init__(self, window: int = 5):
        self.prices: deque[float] = deque(maxlen=window)
        self.entry_price: float | None = None

    # -----------------------------------------------------------------
    #   매수 조건: 최근 n 틱 중 최저가 돌파
    # -----------------------------------------------------------------
    def should_buy(self, tick: dict) -> bool:
        price = tick.get("trade_price")
        if price is None:
            return False

        self.prices.append(price)
        if len(self.prices) < self.prices.maxlen:
            return False
        # 가격이 최저가보다 낮아졌을 때 진입
        return price <= min(self.prices)

    # -----------------------------------------------------------------
    #   매도 조건: 목표 수익 or 손실 도달
    # -----------------------------------------------------------------
    def should_sell(self, tick: dict) -> bool:
        if self.entry_price is None:
            return False

        price = tick.get("trade_price")
        if price is None:
            return False

        gain_pct = (price - self.entry_price) / self.entry_price * 100
        if gain_pct >= TAKE_PROFIT_PCT or gain_pct <= -STOP_LOSS_PCT:
            return True
        return False 