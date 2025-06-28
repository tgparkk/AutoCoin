from __future__ import annotations
from typing import Dict, Any, List

# 다중 종목 지원
SYMBOLS: List[str] = ["KRW-BTC", "KRW-ETH"]  # 거래할 종목 리스트

# 기본 전략 설정
DEFAULT_STRATEGY_CONFIG = {
    "take_profit_pct": 0.5,  # 이익 실현 퍼센트
    "stop_loss_pct": 1.0,    # 손절 퍼센트
    "window": 5,             # 가격 윈도우 크기
}

# 종목별 개별 설정 (기본값 오버라이드)
SYMBOL_SPECIFIC_CONFIG: Dict[str, Dict[str, Any]] = {
    "KRW-BTC": {
        "take_profit_pct": 0.3,
        "stop_loss_pct": 0.8,
        "window": 7,
        # MA Cross 전략 설정
        "fast_period": 5,
        "slow_period": 20,
        # RSI 전략 설정
        "rsi_period": 14,
        "oversold_level": 30,
        "overbought_level": 70,
        # 트레일링 스탑 설정
        "trailing_stop_enabled": True,
        "trailing_stop_pct": 1.0,
        "trailing_activation_pct": 0.5,
        # 부분 청산 설정
        "partial_close_enabled": True,
        "partial_close_levels": [0.5, 1.0, 1.5],
        "partial_close_ratios": [0.3, 0.3, 0.4],
    },
    "KRW-ETH": {
        "take_profit_pct": 0.4,
        "stop_loss_pct": 1.0,
        "window": 5,
        # MA Cross 전략 설정
        "fast_period": 3,
        "slow_period": 15,
        # RSI 전략 설정
        "rsi_period": 12,
        "oversold_level": 25,
        "overbought_level": 75,
        # 트레일링 스탑 설정
        "trailing_stop_enabled": False,
        "trailing_stop_pct": 1.2,
        "trailing_activation_pct": 0.6,
        # 부분 청산 설정
        "partial_close_enabled": True,
        "partial_close_levels": [0.4, 0.8, 1.2],
        "partial_close_ratios": [0.4, 0.3, 0.3],
    }
}

# 종목별 최대 주문 금액 (KRW)
MAX_POSITION_KRW: Dict[str, float] = {
    "KRW-BTC": 200_000,
    "KRW-ETH": 150_000,
}

# 기본 최대 주문 금액 (새 종목 추가 시)
DEFAULT_MAX_POSITION_KRW: float = 100_000

# 전체 포트폴리오 제한
MAX_TOTAL_POSITION_KRW: float = 500_000  # 전체 포지션 합계 제한
MAX_CONCURRENT_POSITIONS: int = 2        # 동시 포지션 수 제한

def get_strategy_config(symbol: str) -> Dict[str, Any]:
    """종목별 전략 설정 반환"""
    config = DEFAULT_STRATEGY_CONFIG.copy()
    
    # 종목별 설정이 있으면 오버라이드
    if symbol in SYMBOL_SPECIFIC_CONFIG:
        config.update(SYMBOL_SPECIFIC_CONFIG[symbol])
    
    return config

def get_max_position_krw(symbol: str) -> float:
    """종목별 최대 주문 금액 반환"""
    return MAX_POSITION_KRW.get(symbol, DEFAULT_MAX_POSITION_KRW)

# 기존 호환성을 위한 변수들
SYMBOL: str = SYMBOLS[0] if SYMBOLS else "KRW-BTC"  # 첫 번째 종목을 기본값으로
TAKE_PROFIT_PCT: float = DEFAULT_STRATEGY_CONFIG["take_profit_pct"]
STOP_LOSS_PCT: float = DEFAULT_STRATEGY_CONFIG["stop_loss_pct"] 