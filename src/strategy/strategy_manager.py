from __future__ import annotations
from typing import Dict, Any, List, Optional, Type
import time
from collections import defaultdict

from .base_strategy import BaseStrategy, OrderFill, PositionType
from .scalping_strategy import ScalpingStrategy
from .ma_cross_strategy import MACrossStrategy
from .rsi_strategy import RSIStrategy
from .advanced_scalping_strategy import AdvancedScalpingStrategy
from config.strategy_config import (
    SYMBOLS, 
    get_strategy_config, 
    get_max_position_krw,
    MAX_TOTAL_POSITION_KRW,
    MAX_CONCURRENT_POSITIONS
)
from src.utils.logger import get_logger

logger = get_logger(__name__)


class StrategyManager:
    """다중 종목 전략 관리자"""
    
    # 사용 가능한 전략 클래스들
    AVAILABLE_STRATEGIES: Dict[str, Type[BaseStrategy]] = {
        "scalping": ScalpingStrategy,
        "ma_cross": MACrossStrategy,
        "rsi": RSIStrategy,
        "advanced_scalping": AdvancedScalpingStrategy,
    }
    
    def __init__(self, strategy_name: str = "scalping"):
        self.strategy_name = strategy_name
        self.strategies: Dict[str, BaseStrategy] = {}
        self.last_tick_times: Dict[str, float] = {}
        
        # 포트폴리오 상태
        self.total_position_value = 0.0
        self.active_positions = 0
        
        # 성과 추적
        self.portfolio_stats = {
            "total_trades": 0,
            "total_pnl": 0.0,
            "symbol_stats": defaultdict(dict)
        }
        
        self._initialize_strategies()
    
    def _initialize_strategies(self) -> None:
        """전략 인스턴스 초기화"""
        if self.strategy_name not in self.AVAILABLE_STRATEGIES:
            raise ValueError(f"지원하지 않는 전략: {self.strategy_name}")
        
        strategy_class = self.AVAILABLE_STRATEGIES[self.strategy_name]
        
        for symbol in SYMBOLS:
            config = get_strategy_config(symbol)
            strategy = strategy_class(symbol, config)
            self.strategies[symbol] = strategy
            
            logger.info("전략 초기화: %s - %s, 설정: %s", symbol, self.strategy_name, config)
    
    def prepare_all_strategies(self, historical_data: Optional[Dict[str, List[Dict]]] = None) -> bool:
        """모든 전략 초기화"""
        success_count = 0
        
        for symbol, strategy in self.strategies.items():
            symbol_data = historical_data.get(symbol) if historical_data else None
            
            if strategy.prepare(symbol_data):
                success_count += 1
                logger.info("전략 준비 완료: %s", symbol)
            else:
                logger.error("전략 준비 실패: %s", symbol)
        
        logger.info("전략 준비 결과: %d/%d 성공", success_count, len(self.strategies))
        return success_count == len(self.strategies)
    
    def process_tick(self, symbol: str, tick: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """종목별 틱 처리"""
        if symbol not in self.strategies:
            logger.warning("알 수 없는 종목: %s", symbol)
            return None
        
        strategy = self.strategies[symbol]
        self.last_tick_times[symbol] = time.time()
        
        # 전략 실행
        signal = strategy.on_tick(tick)
        
        # 포트폴리오 제한 체크
        if signal.get("action") == "buy":
            if not self._can_open_position(symbol, tick.get("trade_price", 0)):
                logger.info("포트폴리오 제한으로 매수 거부: %s", symbol)
                return {"action": "none", "reason": "포트폴리오 제한"}
        
        return signal
    
    def process_order_fill(self, symbol: str, fill: OrderFill) -> None:
        """주문 체결 처리"""
        if symbol not in self.strategies:
            logger.warning("알 수 없는 종목 체결: %s", symbol)
            return
        
        strategy = self.strategies[symbol]
        strategy.on_order_fill(fill)
        
        # 포트폴리오 통계 업데이트
        self._update_portfolio_stats(symbol, fill)
        
        logger.info("체결 처리 완료: %s %s @ %s", symbol, fill.side, fill.price)
    
    def _can_open_position(self, symbol: str, price: float) -> bool:
        """포지션 오픈 가능 여부 체크"""
        # 1. 동시 포지션 수 제한
        if self.active_positions >= MAX_CONCURRENT_POSITIONS:
            return False
        
        # 2. 종목별 최대 금액 제한
        max_krw = get_max_position_krw(symbol)
        if max_krw <= 0:
            return False
        
        # 3. 전체 포트폴리오 제한
        if self.total_position_value + max_krw > MAX_TOTAL_POSITION_KRW:
            return False
        
        return True
    
    def _update_portfolio_stats(self, symbol: str, fill: OrderFill) -> None:
        """포트폴리오 통계 업데이트"""
        strategy = self.strategies[symbol]
        
        if fill.side == "buy":
            self.active_positions += 1
            self.total_position_value += fill.price * fill.volume
        else:
            self.active_positions = max(0, self.active_positions - 1)
            self.total_position_value = max(0, self.total_position_value - fill.price * fill.volume)
        
        # 전체 통계
        self.portfolio_stats["total_trades"] += 1
        self.portfolio_stats["total_pnl"] += strategy.total_pnl
        
        # 종목별 통계
        self.portfolio_stats["symbol_stats"][symbol] = strategy.get_performance_stats()
    
    def get_portfolio_status(self) -> Dict[str, Any]:
        """포트폴리오 전체 상태 반환"""
        positions = {}
        total_unrealized_pnl = 0.0
        
        for symbol, strategy in self.strategies.items():
            pos_info = strategy.get_position_info()
            positions[symbol] = pos_info
            total_unrealized_pnl += pos_info["unrealized_pnl"]
        
        return {
            "active_positions": self.active_positions,
            "total_position_value": round(self.total_position_value, 2),
            "total_unrealized_pnl": round(total_unrealized_pnl, 2),
            "total_realized_pnl": round(self.portfolio_stats["total_pnl"], 2),
            "positions": positions,
            "limits": {
                "max_concurrent_positions": MAX_CONCURRENT_POSITIONS,
                "max_total_position_krw": MAX_TOTAL_POSITION_KRW
            }
        }
    
    def get_strategy_performance(self) -> Dict[str, Any]:
        """전략 성과 반환"""
        total_trades = sum(s.total_trades for s in self.strategies.values())
        total_winning = sum(s.winning_trades for s in self.strategies.values())
        total_pnl = sum(s.total_pnl for s in self.strategies.values())
        
        win_rate = (total_winning / total_trades * 100) if total_trades > 0 else 0.0
        
        return {
            "strategy_name": self.strategy_name,
            "total_trades": total_trades,
            "winning_trades": total_winning,
            "win_rate": round(win_rate, 2),
            "total_pnl": round(total_pnl, 2),
            "symbol_performance": {
                symbol: strategy.get_performance_stats() 
                for symbol, strategy in self.strategies.items()
            }
        }
    
    def reset_all_strategies(self) -> None:
        """모든 전략 상태 초기화"""
        for strategy in self.strategies.values():
            strategy.reset()
        
        self.total_position_value = 0.0
        self.active_positions = 0
        self.portfolio_stats = {
            "total_trades": 0,
            "total_pnl": 0.0,
            "symbol_stats": defaultdict(dict)
        }
        
        logger.info("모든 전략 상태 초기화 완료")
    
    def get_strategy_info(self) -> Dict[str, Any]:
        """전략 정보 반환"""
        return {
            "strategy_name": self.strategy_name,
            "symbols": list(self.strategies.keys()),
            "strategy_configs": {
                symbol: get_strategy_config(symbol) 
                for symbol in self.strategies.keys()
            }
        } 