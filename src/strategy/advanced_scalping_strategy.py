from __future__ import annotations
from collections import deque
from typing import Dict, Any, Optional, List

from .base_strategy import BaseStrategy, PositionType
from .trailing_stop_mixin import TrailingStopMixin


class AdvancedScalpingStrategy(TrailingStopMixin, BaseStrategy):
    """트레일링 스탑과 부분 청산을 지원하는 고급 스캘핑 전략"""

    def __init__(self, symbol: str, config: Dict[str, Any] = None):
        super().__init__(symbol, config)
        
        # 기본 스캘핑 파라미터
        self.window = config.get("window", 5) if config else 5
        self.take_profit_pct = config.get("take_profit_pct", 0.8) if config else 0.8
        self.stop_loss_pct = config.get("stop_loss_pct", 1.2) if config else 1.2
        
        # 상태 변수
        self.prices: deque[float] = deque(maxlen=self.window)

    def _prepare_indicators(self, historical_data: Optional[List[Dict]] = None) -> None:
        """지표 초기화"""
        self.prices.clear()
        
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
        
        # 1) 포지션이 없을 때 - 매수 조건 체크
        if self.position.position_type == PositionType.NONE:
            if self._should_enter_long(price):
                return {
                    "action": "buy",
                    "price": price,
                    "reason": "가격 반전 진입 신호"
                }
        
        # 2) 포지션이 있을 때 - 매도 조건 체크
        elif self.position.position_type == PositionType.LONG:
            # 트레일링 스탑 체크
            trailing_signal = self.update_trailing_stop(price)
            if trailing_signal:
                return trailing_signal
            
            # 부분 청산 체크
            partial_signal = self.check_partial_close(price)
            if partial_signal:
                return partial_signal
            
            # 기본 청산 조건 체크
            exit_reason = self._should_exit_long(price)
            if exit_reason:
                return {
                    "action": "sell",
                    "price": price,
                    "volume": self.remaining_volume,
                    "reason": exit_reason
                }
        
        return {"action": "none"}

    def _should_enter_long(self, current_price: float) -> bool:
        """매수 진입 조건"""
        if len(self.prices) < self.window:
            return False
        
        # 최근 n 틱 중 최저가 돌파 시 진입
        min_price = min(self.prices)
        return current_price <= min_price

    def _should_exit_long(self, current_price: float) -> Optional[str]:
        """기본 매도 조건"""
        if self.position.entry_price <= 0:
            return None
        
        gain_pct = (current_price - self.position.entry_price) / self.position.entry_price * 100
        
        # 목표 수익 또는 손절 도달 (트레일링/부분청산이 활성화된 경우 더 관대하게)
        take_profit_threshold = self.take_profit_pct
        stop_loss_threshold = self.stop_loss_pct
        
        # 트레일링 스탑이나 부분 청산이 활성화된 경우 기본 청산 조건을 완화
        if self.trailing_stop_enabled or self.partial_close_enabled:
            take_profit_threshold *= 1.5  # 50% 더 관대하게
            stop_loss_threshold *= 0.8    # 20% 더 엄격하게
        
        if gain_pct >= take_profit_threshold:
            return f"목표 수익 달성 ({gain_pct:.2f}%)"
        elif gain_pct <= -stop_loss_threshold:
            return f"손절 실행 ({gain_pct:.2f}%)"
        
        return None

    def _on_position_opened(self, fill) -> None:
        """포지션 오픈 후 처리"""
        super()._on_position_opened(fill)
        
        # 트레일링 스탑과 부분 청산 설정
        self.setup_position_tracking(fill.price, fill.volume)
        
        self.state["last_entry_time"] = fill.timestamp
        self.state["entry_reason"] = "가격 반전 진입"

    def _on_position_closed(self, fill) -> None:
        """포지션 클로즈 후 처리"""
        super()._on_position_closed(fill)
        
        # 포지션 추적 초기화
        self.reset_position_tracking()
        
        if "last_entry_time" in self.state:
            hold_time = fill.timestamp - self.state["last_entry_time"]
            self.state["last_hold_time"] = hold_time

    def get_strategy_info(self) -> Dict[str, Any]:
        """전략별 정보 반환"""
        base_info = {
            "strategy_name": "AdvancedScalpingStrategy",
            "window": self.window,
            "take_profit_pct": self.take_profit_pct,
            "stop_loss_pct": self.stop_loss_pct,
            "price_buffer_size": len(self.prices),
            "last_hold_time": self.state.get("last_hold_time", 0)
        }
        
        # 트레일링 스탑 정보 추가
        base_info.update(self.get_trailing_stop_info())
        
        # 부분 청산 정보 추가
        base_info.update(self.get_partial_close_info())
        
        return base_info 