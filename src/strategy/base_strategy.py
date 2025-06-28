from __future__ import annotations
from abc import ABC, abstractmethod


class BaseStrategy(ABC):
    @abstractmethod
    def should_buy(self, tick: dict) -> bool:
        """매수 조건 판단"""

    @abstractmethod
    def should_sell(self, tick: dict) -> bool:
        """매도 조건 판단""" 