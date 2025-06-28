from __future__ import annotations
from collections import deque
from typing import Dict, Any, Optional, List

from .base_strategy import BaseStrategy, PositionType


class RSIStrategy(BaseStrategy):
    """RSI 기반 과매수/과매도 전략"""

    def __init__(self, symbol: str, config: Dict[str, Any] = None):
        super().__init__(symbol, config)
        
        # 전략 파라미터
        self.rsi_period = config.get("rsi_period", 14) if config else 14
        self.oversold_level = config.get("oversold_level", 30) if config else 30
        self.overbought_level = config.get("overbought_level", 70) if config else 70
        self.take_profit_pct = config.get("take_profit_pct", 1.5) if config else 1.5
        self.stop_loss_pct = config.get("stop_loss_pct", 2.0) if config else 2.0
        
        # RSI 계산용 데이터
        self.prices: deque[float] = deque(maxlen=self.rsi_period + 1)
        self.gains: deque[float] = deque(maxlen=self.rsi_period)
        self.losses: deque[float] = deque(maxlen=self.rsi_period)
        
        # RSI 값
        self.current_rsi = 50.0
        self.prev_rsi = 50.0
        
        # 평균 계산용
        self.avg_gain = 0.0
        self.avg_loss = 0.0

    def _prepare_indicators(self, historical_data: Optional[List[Dict]] = None) -> None:
        """지표 초기화"""
        self.prices.clear()
        self.gains.clear()
        self.losses.clear()
        
        if historical_data and len(historical_data) > self.rsi_period:
            # 과거 데이터로 RSI 초기화
            for data in historical_data[-(self.rsi_period + 10):]:
                price = data.get("trade_price") or data.get("close")
                if price:
                    self._add_price(float(price))

    def _process_tick(self, tick: Dict[str, Any]) -> Dict[str, Any]:
        """틱 처리 로직"""
        price = tick.get("trade_price")
        if price is None:
            return {"action": "none"}
        
        price = float(price)
        self.prev_rsi = self.current_rsi
        
        # 새 가격 추가 및 RSI 계산
        self._add_price(price)
        self._calculate_rsi()
        
        # 충분한 데이터가 없으면 대기
        if len(self.gains) < self.rsi_period:
            return {"action": "none"}
        
        # 1) 매수 조건 체크 (과매도에서 반등)
        if self.position.position_type == PositionType.NONE:
            if self._is_oversold_reversal():
                return {
                    "action": "buy",
                    "price": price,
                    "reason": f"과매도 반등 신호 (RSI: {self.current_rsi:.2f})"
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

    def _add_price(self, price: float) -> None:
        """가격 추가 및 gain/loss 계산"""
        if len(self.prices) > 0:
            price_change = price - self.prices[-1]
            
            if price_change > 0:
                self.gains.append(price_change)
                self.losses.append(0.0)
            else:
                self.gains.append(0.0)
                self.losses.append(abs(price_change))
        
        self.prices.append(price)

    def _calculate_rsi(self) -> None:
        """RSI 계산"""
        if len(self.gains) < self.rsi_period:
            return
        
        # 첫 번째 계산 (단순 평균)
        if self.avg_gain == 0 and self.avg_loss == 0:
            self.avg_gain = sum(self.gains) / self.rsi_period
            self.avg_loss = sum(self.losses) / self.rsi_period
        else:
            # 지수 이동평균 방식 (Wilder's smoothing)
            latest_gain = self.gains[-1]
            latest_loss = self.losses[-1]
            
            self.avg_gain = (self.avg_gain * (self.rsi_period - 1) + latest_gain) / self.rsi_period
            self.avg_loss = (self.avg_loss * (self.rsi_period - 1) + latest_loss) / self.rsi_period
        
        # RSI 계산
        if self.avg_loss == 0:
            self.current_rsi = 100.0
        else:
            rs = self.avg_gain / self.avg_loss
            self.current_rsi = 100 - (100 / (1 + rs))

    def _is_oversold_reversal(self) -> bool:
        """과매도에서 반등 신호 확인"""
        # 이전 RSI가 과매도 구간에 있고, 현재 RSI가 상승 중
        return (self.prev_rsi <= self.oversold_level and 
                self.current_rsi > self.prev_rsi and
                self.current_rsi > self.oversold_level)

    def _is_overbought_condition(self) -> bool:
        """과매수 조건 확인"""
        return self.current_rsi >= self.overbought_level

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
        
        # 2. 과매수 청산
        if self._is_overbought_condition():
            return f"과매수 청산 (RSI: {self.current_rsi:.2f})"
        
        return None

    def _on_position_opened(self, fill) -> None:
        """포지션 오픈 후 처리"""
        self.state["entry_rsi"] = self.current_rsi
        self.state["entry_time"] = fill.timestamp

    def _on_position_closed(self, fill) -> None:
        """포지션 클로즈 후 처리"""
        self.state["exit_rsi"] = self.current_rsi
        if "entry_time" in self.state:
            hold_time = fill.timestamp - self.state["entry_time"]
            self.state["hold_time"] = hold_time

    def get_strategy_info(self) -> Dict[str, Any]:
        """전략별 정보 반환"""
        return {
            "strategy_name": "RSIStrategy",
            "rsi_period": self.rsi_period,
            "oversold_level": self.oversold_level,
            "overbought_level": self.overbought_level,
            "take_profit_pct": self.take_profit_pct,
            "stop_loss_pct": self.stop_loss_pct,
            "current_rsi": round(self.current_rsi, 2),
            "avg_gain": round(self.avg_gain, 4),
            "avg_loss": round(self.avg_loss, 4),
            "price_buffer_size": len(self.prices)
        } 