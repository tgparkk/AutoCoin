from __future__ import annotations
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
import time


@dataclass
class PartialPosition:
    """부분 포지션 정보"""
    volume: float
    entry_price: float
    entry_time: float
    is_closed: bool = False
    close_price: float = 0.0
    close_time: float = 0.0


class TrailingStopMixin:
    """트레일링 스탑과 부분 청산 기능을 제공하는 믹스인"""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # 트레일링 스탑 설정
        self.trailing_stop_enabled = kwargs.get("trailing_stop_enabled", False)
        self.trailing_stop_pct = kwargs.get("trailing_stop_pct", 1.0)
        self.trailing_activation_pct = kwargs.get("trailing_activation_pct", 0.5)
        
        # 부분 청산 설정
        self.partial_close_enabled = kwargs.get("partial_close_enabled", False)
        self.partial_close_levels = kwargs.get("partial_close_levels", [0.5, 1.0, 1.5])  # 수익률 %
        self.partial_close_ratios = kwargs.get("partial_close_ratios", [0.3, 0.3, 0.4])  # 청산 비율
        
        # 트레일링 스탑 상태
        self.highest_price = 0.0
        self.trailing_stop_price = 0.0
        self.trailing_active = False
        
        # 부분 청산 상태
        self.partial_positions: List[PartialPosition] = []
        self.next_partial_level_idx = 0
        self.remaining_volume = 0.0

    def setup_position_tracking(self, entry_price: float, volume: float) -> None:
        """포지션 추적 설정"""
        self.highest_price = entry_price
        self.trailing_stop_price = 0.0
        self.trailing_active = False
        
        # 부분 청산을 위한 포지션 분할
        if self.partial_close_enabled:
            self._setup_partial_positions(entry_price, volume)
        else:
            self.remaining_volume = volume

    def _setup_partial_positions(self, entry_price: float, total_volume: float) -> None:
        """부분 포지션 설정"""
        self.partial_positions.clear()
        self.next_partial_level_idx = 0
        
        # 비율에 따라 포지션 분할
        for i, ratio in enumerate(self.partial_close_ratios):
            volume = total_volume * ratio
            self.partial_positions.append(
                PartialPosition(
                    volume=volume,
                    entry_price=entry_price,
                    entry_time=time.time()
                )
            )
        
        self.remaining_volume = total_volume

    def update_trailing_stop(self, current_price: float) -> Optional[Dict[str, Any]]:
        """트레일링 스탑 업데이트"""
        if not self.trailing_stop_enabled or self.position.entry_price <= 0:
            return None
        
        # 최고가 업데이트
        if current_price > self.highest_price:
            self.highest_price = current_price
        
        # 트레일링 활성화 체크
        entry_gain_pct = (current_price - self.position.entry_price) / self.position.entry_price * 100
        
        if not self.trailing_active and entry_gain_pct >= self.trailing_activation_pct:
            self.trailing_active = True
            self.trailing_stop_price = self.highest_price * (1 - self.trailing_stop_pct / 100)
        
        # 트레일링 스탑 가격 업데이트
        if self.trailing_active:
            new_stop_price = self.highest_price * (1 - self.trailing_stop_pct / 100)
            if new_stop_price > self.trailing_stop_price:
                self.trailing_stop_price = new_stop_price
            
            # 트레일링 스탑 트리거 체크
            if current_price <= self.trailing_stop_price:
                return {
                    "action": "sell",
                    "price": current_price,
                    "volume": self.remaining_volume,
                    "reason": f"트레일링 스탑 실행 (최고가: {self.highest_price:.2f}, 스탑: {self.trailing_stop_price:.2f})"
                }
        
        return None

    def check_partial_close(self, current_price: float) -> Optional[Dict[str, Any]]:
        """부분 청산 체크"""
        if not self.partial_close_enabled or self.position.entry_price <= 0:
            return None
        
        if self.next_partial_level_idx >= len(self.partial_close_levels):
            return None
        
        # 현재 수익률 계산
        gain_pct = (current_price - self.position.entry_price) / self.position.entry_price * 100
        target_level = self.partial_close_levels[self.next_partial_level_idx]
        
        if gain_pct >= target_level:
            # 해당 레벨의 포지션 청산
            position_to_close = self.partial_positions[self.next_partial_level_idx]
            
            if not position_to_close.is_closed:
                position_to_close.is_closed = True
                position_to_close.close_price = current_price
                position_to_close.close_time = time.time()
                
                self.remaining_volume -= position_to_close.volume
                self.next_partial_level_idx += 1
                
                return {
                    "action": "sell",
                    "price": current_price,
                    "volume": position_to_close.volume,
                    "reason": f"부분 청산 {self.next_partial_level_idx}/{len(self.partial_close_levels)} ({gain_pct:.2f}%)"
                }
        
        return None

    def get_trailing_stop_info(self) -> Dict[str, Any]:
        """트레일링 스탑 정보 반환"""
        return {
            "trailing_stop_enabled": self.trailing_stop_enabled,
            "trailing_active": self.trailing_active,
            "highest_price": self.highest_price,
            "trailing_stop_price": self.trailing_stop_price,
            "trailing_stop_pct": self.trailing_stop_pct,
            "trailing_activation_pct": self.trailing_activation_pct
        }

    def get_partial_close_info(self) -> Dict[str, Any]:
        """부분 청산 정보 반환"""
        closed_positions = [p for p in self.partial_positions if p.is_closed]
        open_positions = [p for p in self.partial_positions if not p.is_closed]
        
        return {
            "partial_close_enabled": self.partial_close_enabled,
            "total_positions": len(self.partial_positions),
            "closed_positions": len(closed_positions),
            "open_positions": len(open_positions),
            "remaining_volume": self.remaining_volume,
            "next_level_idx": self.next_partial_level_idx,
            "next_target_level": (
                self.partial_close_levels[self.next_partial_level_idx] 
                if self.next_partial_level_idx < len(self.partial_close_levels) 
                else None
            )
        }

    def reset_position_tracking(self) -> None:
        """포지션 추적 초기화"""
        self.highest_price = 0.0
        self.trailing_stop_price = 0.0
        self.trailing_active = False
        self.partial_positions.clear()
        self.next_partial_level_idx = 0
        self.remaining_volume = 0.0 