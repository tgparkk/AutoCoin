class RiskManager:
    """간단한 리스크 관리 로직"""

    def __init__(self, max_position_krw: float):
        self.max_position_krw = max_position_krw

    def allow_order(self, current_position_krw: float) -> bool:
        """현재 보유 현금으로 주문이 가능한지 여부"""
        return current_position_krw >= 1000 and current_position_krw >= self.max_position_krw * 0.1 