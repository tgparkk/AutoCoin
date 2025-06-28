from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from enum import Enum
import time


class PositionType(Enum):
    """포지션 타입"""
    NONE = "none"
    LONG = "long"
    SHORT = "short"


@dataclass
class Position:
    """포지션 정보"""
    symbol: str
    position_type: PositionType
    entry_price: float
    volume: float
    entry_time: float
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0


@dataclass
class OrderFill:
    """주문 체결 정보"""
    symbol: str
    side: str  # "buy" | "sell"
    price: float
    volume: float
    timestamp: float
    order_id: str


class BaseStrategy(ABC):
    """전략 기본 클래스 - 모든 전략이 상속받아야 함"""
    
    def __init__(self, symbol: str, config: Dict[str, Any] = None):
        self.symbol = symbol
        self.config = config or {}
        self.position = Position(
            symbol=symbol,
            position_type=PositionType.NONE,
            entry_price=0.0,
            volume=0.0,
            entry_time=0.0
        )
        self.is_initialized = False
        self.last_tick_time = 0.0
        self.tick_count = 0
        
        # 전략별 상태 저장소
        self.state: Dict[str, Any] = {}
        
        # 성과 추적
        self.total_trades = 0
        self.winning_trades = 0
        self.total_pnl = 0.0
        
    def prepare(self, historical_data: Optional[List[Dict]] = None) -> bool:
        """전략 초기화 - 과거 데이터로 지표 계산 등"""
        try:
            self._prepare_indicators(historical_data)
            self.is_initialized = True
            return True
        except Exception as e:
            print(f"전략 초기화 실패: {e}")
            return False
    
    @abstractmethod
    def _prepare_indicators(self, historical_data: Optional[List[Dict]] = None) -> None:
        """지표 초기화 - 각 전략에서 구현"""
        pass
    
    def on_tick(self, tick: Dict[str, Any]) -> Dict[str, Any]:
        """틱 데이터 수신 시 호출"""
        if not self.is_initialized:
            return {"action": "none"}
        
        self.last_tick_time = time.time()
        self.tick_count += 1
        
        # 현재 가격으로 미실현 손익 업데이트
        current_price = tick.get("trade_price", 0.0)
        self._update_unrealized_pnl(current_price)
        
        # 전략별 틱 처리
        return self._process_tick(tick)
    
    @abstractmethod
    def _process_tick(self, tick: Dict[str, Any]) -> Dict[str, Any]:
        """틱 처리 로직 - 각 전략에서 구현
        
        Returns:
            {"action": "buy|sell|none", "price": float, "volume": float, "reason": str}
        """
        pass
    
    def on_order_fill(self, fill: OrderFill) -> None:
        """주문 체결 시 호출"""
        self.total_trades += 1
        
        if fill.side == "buy":
            self._on_buy_fill(fill)
        else:
            self._on_sell_fill(fill)
    
    def _on_buy_fill(self, fill: OrderFill) -> None:
        """매수 체결 처리"""
        self.position.position_type = PositionType.LONG
        self.position.entry_price = fill.price
        self.position.volume = fill.volume
        self.position.entry_time = fill.timestamp
        self.position.unrealized_pnl = 0.0
        
        # 전략별 매수 후 처리
        self._on_position_opened(fill)
    
    def _on_sell_fill(self, fill: OrderFill) -> None:
        """매도 체결 처리"""
        if self.position.position_type == PositionType.LONG:
            # 실현 손익 계산
            pnl = (fill.price - self.position.entry_price) * self.position.volume
            self.position.realized_pnl += pnl
            self.total_pnl += pnl
            
            if pnl > 0:
                self.winning_trades += 1
        
        # 포지션 초기화
        self.position.position_type = PositionType.NONE
        self.position.entry_price = 0.0
        self.position.volume = 0.0
        self.position.unrealized_pnl = 0.0
        
        # 전략별 매도 후 처리
        self._on_position_closed(fill)
    
    def _on_position_opened(self, fill: OrderFill) -> None:
        """포지션 오픈 후 처리 - 각 전략에서 오버라이드 가능"""
        pass
    
    def _on_position_closed(self, fill: OrderFill) -> None:
        """포지션 클로즈 후 처리 - 각 전략에서 오버라이드 가능"""
        pass
    
    def _update_unrealized_pnl(self, current_price: float) -> None:
        """미실현 손익 업데이트"""
        if self.position.position_type == PositionType.LONG:
            self.position.unrealized_pnl = (current_price - self.position.entry_price) * self.position.volume
    
    def get_position_info(self) -> Dict[str, Any]:
        """현재 포지션 정보 반환"""
        return {
            "symbol": self.position.symbol,
            "position_type": self.position.position_type.value,
            "entry_price": self.position.entry_price,
            "volume": self.position.volume,
            "unrealized_pnl": self.position.unrealized_pnl,
            "realized_pnl": self.position.realized_pnl
        }
    
    def get_performance_stats(self) -> Dict[str, Any]:
        """성과 통계 반환"""
        win_rate = (self.winning_trades / self.total_trades * 100) if self.total_trades > 0 else 0.0
        
        return {
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "win_rate": round(win_rate, 2),
            "total_pnl": round(self.total_pnl, 2),
            "tick_count": self.tick_count
        }
    
    def reset(self) -> None:
        """전략 상태 초기화"""
        self.position = Position(
            symbol=self.symbol,
            position_type=PositionType.NONE,
            entry_price=0.0,
            volume=0.0,
            entry_time=0.0
        )
        self.state.clear()
        self.is_initialized = False
        self.tick_count = 0
        self.total_trades = 0
        self.winning_trades = 0
        self.total_pnl = 0.0

    # 기존 호환성을 위한 메서드들
    def should_buy(self, tick: dict) -> bool:
        """매수 조건 판단 (기존 호환성)"""
        result = self.on_tick(tick)
        return result.get("action") == "buy"

    def should_sell(self, tick: dict) -> bool:
        """매도 조건 판단 (기존 호환성)"""
        result = self.on_tick(tick)
        return result.get("action") == "sell" 