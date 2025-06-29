from __future__ import annotations
from collections import deque
from typing import Dict, Any, Optional, List

from config.strategy_config import TAKE_PROFIT_PCT, STOP_LOSS_PCT
from .base_strategy import BaseStrategy, PositionType


class ScalpingStrategy(BaseStrategy):
    """단순 가격 반전 기반 스캘핑 전략"""

    def __init__(self, symbol: str, config: Dict[str, Any] = None):
        super().__init__(symbol, config)
        
        # 전략 파라미터
        self.window = config.get("window", 5) if config else 5
        self.take_profit_pct = config.get("take_profit_pct", TAKE_PROFIT_PCT) if config else TAKE_PROFIT_PCT
        self.stop_loss_pct = config.get("stop_loss_pct", STOP_LOSS_PCT) if config else STOP_LOSS_PCT
        
        # 상태 변수
        self.prices: deque[float] = deque(maxlen=self.window)

        # 호가 기반 필터링
        self.max_spread = config.get("max_allowed_spread", 1000) if config else 1000  # KRW 단위 허용 스프레드
        self.best_bid: float | None = None
        self.best_ask: float | None = None

    def _prepare_indicators(self, historical_data: Optional[List[Dict]] = None) -> None:
        """지표 초기화"""
        self.prices.clear()
        
        # 과거 데이터가 있으면 초기화에 사용
        if historical_data:
            for data in historical_data[-self.window:]:
                price = data.get("trade_price") or data.get("close")
                if price:
                    self.prices.append(float(price))

    def _process_tick(self, tick: Dict[str, Any]) -> Dict[str, Any]:
        """틱 처리 로직"""
        price = tick.get("trade_price")
        if price is None:
            return {"action": "none"}
        
        price = float(price)
        self.prices.append(price)
        
        # 1) 매수 조건 체크
        if self.position.position_type == PositionType.NONE:
            if self._should_enter_long(price):
                return {
                    "action": "buy",
                    "price": price,
                    "reason": "가격 반전 진입 신호"
                }
        
        # 2) 매도 조건 체크
        elif self.position.position_type == PositionType.LONG:
            if self._should_exit_long(price):
                return {
                    "action": "sell",
                    "price": price,
                    "reason": self._get_exit_reason(price)
                }
        
        return {"action": "none"}

    def _should_enter_long(self, current_price: float) -> bool:
        """매수 진입 조건"""
        if len(self.prices) < self.window:
            return False
        
        # 최근 n 틱 중 최저가 돌파 시 진입
        min_price = min(self.prices)
        return current_price <= min_price

    def _should_exit_long(self, current_price: float) -> bool:
        """매도 청산 조건"""
        if self.position.entry_price <= 0:
            return False
        
        gain_pct = (current_price - self.position.entry_price) / self.position.entry_price * 100
        
        # 목표 수익 또는 손절 도달
        return gain_pct >= self.take_profit_pct or gain_pct <= -self.stop_loss_pct

    def _get_exit_reason(self, current_price: float) -> str:
        """청산 사유 반환"""
        gain_pct = (current_price - self.position.entry_price) / self.position.entry_price * 100
        
        if gain_pct >= self.take_profit_pct:
            return f"목표 수익 달성 ({gain_pct:.2f}%)"
        elif gain_pct <= -self.stop_loss_pct:
            return f"손절 실행 ({gain_pct:.2f}%)"
        else:
            return "기타"

    def _on_position_opened(self, fill) -> None:
        """포지션 오픈 후 처리"""
        self.state["last_entry_time"] = fill.timestamp
        self.state["entry_reason"] = "가격 반전 진입"

    def _on_position_closed(self, fill) -> None:
        """포지션 클로즈 후 처리"""
        if "last_entry_time" in self.state:
            hold_time = fill.timestamp - self.state["last_entry_time"]
            self.state["last_hold_time"] = hold_time

    def get_strategy_info(self) -> Dict[str, Any]:
        """전략별 정보 반환"""
        return {
            "strategy_name": "ScalpingStrategy",
            "window": self.window,
            "take_profit_pct": self.take_profit_pct,
            "stop_loss_pct": self.stop_loss_pct,
            "max_spread": self.max_spread,
            "price_buffer_size": len(self.prices),
            "last_hold_time": self.state.get("last_hold_time", 0)
        }

    # ------------------------------------------------------------------
    # 주문book/스프레드 필터링용 on_tick 오버라이드
    # ------------------------------------------------------------------

    def on_tick(self, tick: Dict[str, Any]) -> Dict[str, Any]:
        """호가(orderbook) 메시지를 우선 처리한 뒤 기본 로직 호출"""

        # 1) ORDERBOOK 메시지: 호가 정보만 저장
        if tick.get("type") == "orderbook":
            self.best_bid = tick.get("best_bid")
            self.best_ask = tick.get("best_ask")
            return {"action": "none"}

        # 2) 스프레드가 과도하면 거래 skip
        if self.best_bid is None or self.best_ask is None:
            return {"action": "none"}

        spread = self.best_ask - self.best_bid
        if spread > self.max_spread:
            return {"action": "none"}

        # 3) 정상적인 ticker → 기존 로직 진행
        return super().on_tick(tick) 