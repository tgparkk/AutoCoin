from __future__ import annotations
from collections import deque
from typing import Dict, Any, Optional, List

from .base_strategy import BaseStrategy, PositionType


class MACrossStrategy(BaseStrategy):
    """이동평균 교차 전략"""

    def __init__(self, symbol: str, config: Dict[str, Any] = None):
        super().__init__(symbol, config)
        
        # 전략 파라미터
        self.fast_period = config.get("fast_period", 5) if config else 5
        self.slow_period = config.get("slow_period", 20) if config else 20
        self.take_profit_pct = config.get("take_profit_pct", 1.0) if config else 1.0
        self.stop_loss_pct = config.get("stop_loss_pct", 2.0) if config else 2.0
        
        # 가격 데이터 저장
        self.prices: deque[float] = deque(maxlen=max(self.fast_period, self.slow_period))
        
        # 이동평균 값들
        self.fast_ma = 0.0
        self.slow_ma = 0.0
        self.prev_fast_ma = 0.0
        self.prev_slow_ma = 0.0

    def _prepare_indicators(self, historical_data: Optional[List[Dict]] = None) -> None:
        """지표 초기화"""
        self.prices.clear()
        
        if historical_data:
            # 과거 데이터로 이동평균 초기화
            for data in historical_data[-self.slow_period:]:
                price = data.get("trade_price") or data.get("close")
                if price:
                    self.prices.append(float(price))
            
            # 초기 이동평균 계산
            if len(self.prices) >= self.slow_period:
                self._calculate_moving_averages()

    def _process_tick(self, tick: Dict[str, Any]) -> Dict[str, Any]:
        """틱 처리 로직"""
        price = tick.get("trade_price")
        if price is None:
            return {"action": "none"}
        
        price = float(price)
        
        # 이전 이동평균 저장
        self.prev_fast_ma = self.fast_ma
        self.prev_slow_ma = self.slow_ma
        
        # 새 가격 추가 및 이동평균 계산
        self.prices.append(price)
        self._calculate_moving_averages()
        
        # 충분한 데이터가 없으면 대기
        if len(self.prices) < self.slow_period:
            return {"action": "none"}
        
        # 1) 매수 조건 체크 (골든 크로스)
        if self.position.position_type == PositionType.NONE:
            if self._is_golden_cross():
                return {
                    "action": "buy",
                    "price": price,
                    "reason": f"골든 크로스 (Fast MA: {self.fast_ma:.2f}, Slow MA: {self.slow_ma:.2f})"
                }
        
        # 2) 매도 조건 체크
        elif self.position.position_type == PositionType.LONG:
            exit_reason = self._should_exit_long(price)
            if exit_reason:
                return {
                    "action": "sell",
                    "price": price,
                    "reason": exit_reason
                }
        
        return {"action": "none"}

    def _calculate_moving_averages(self) -> None:
        """이동평균 계산"""
        if len(self.prices) >= self.fast_period:
            self.fast_ma = sum(list(self.prices)[-self.fast_period:]) / self.fast_period
        
        if len(self.prices) >= self.slow_period:
            self.slow_ma = sum(list(self.prices)[-self.slow_period:]) / self.slow_period

    def _is_golden_cross(self) -> bool:
        """골든 크로스 확인 (빠른 MA가 느린 MA를 상향 돌파)"""
        if self.prev_fast_ma == 0 or self.prev_slow_ma == 0:
            return False
        
        # 이전: 빠른 MA <= 느린 MA, 현재: 빠른 MA > 느린 MA
        return (self.prev_fast_ma <= self.prev_slow_ma and 
                self.fast_ma > self.slow_ma)

    def _is_death_cross(self) -> bool:
        """데스 크로스 확인 (빠른 MA가 느린 MA를 하향 돌파)"""
        if self.prev_fast_ma == 0 or self.prev_slow_ma == 0:
            return False
        
        # 이전: 빠른 MA >= 느린 MA, 현재: 빠른 MA < 느린 MA
        return (self.prev_fast_ma >= self.prev_slow_ma and 
                self.fast_ma < self.slow_ma)

    def _should_exit_long(self, current_price: float) -> Optional[str]:
        """매도 조건 확인"""
        if self.position.entry_price <= 0:
            return None
        
        # 1. 손익 기준 청산
        gain_pct = (current_price - self.position.entry_price) / self.position.entry_price * 100
        
        if gain_pct >= self.take_profit_pct:
            return f"목표 수익 달성 ({gain_pct:.2f}%)"
        elif gain_pct <= -self.stop_loss_pct:
            return f"손절 실행 ({gain_pct:.2f}%)"
        
        # 2. 데스 크로스 청산
        if self._is_death_cross():
            return f"데스 크로스 청산 (Fast MA: {self.fast_ma:.2f}, Slow MA: {self.slow_ma:.2f})"
        
        return None

    def _on_position_opened(self, fill) -> None:
        """포지션 오픈 후 처리"""
        self.state["entry_fast_ma"] = self.fast_ma
        self.state["entry_slow_ma"] = self.slow_ma
        self.state["entry_spread"] = self.fast_ma - self.slow_ma

    def _on_position_closed(self, fill) -> None:
        """포지션 클로즈 후 처리"""
        if "entry_fast_ma" in self.state:
            exit_spread = self.fast_ma - self.slow_ma
            self.state["exit_spread"] = exit_spread
            self.state["spread_change"] = exit_spread - self.state.get("entry_spread", 0)

    def get_strategy_info(self) -> Dict[str, Any]:
        """전략별 정보 반환"""
        return {
            "strategy_name": "MACrossStrategy",
            "fast_period": self.fast_period,
            "slow_period": self.slow_period,
            "take_profit_pct": self.take_profit_pct,
            "stop_loss_pct": self.stop_loss_pct,
            "current_fast_ma": round(self.fast_ma, 2),
            "current_slow_ma": round(self.slow_ma, 2),
            "ma_spread": round(self.fast_ma - self.slow_ma, 2),
            "price_buffer_size": len(self.prices)
        } 