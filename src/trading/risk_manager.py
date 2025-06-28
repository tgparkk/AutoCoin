class RiskManager:
    """리스크 관리 로직

    주문 전 다음 항목을 검증한다.
    1) 일일 손실 한도(Stop-Day)
    2) 자산 비중 한도(코인 평가액 / 총자산)
    3) 최대 동시 포지션 수 한도
    4) 최소·최대 주문 금액 한도
    """

    def __init__(self, max_position_krw: float):
        self.max_position_krw = max_position_krw
        # 마지막으로 리셋한 날짜(YYYY-MM-DD)
        self._last_reset_date: str | None = None

    def allow_order(
        self,
        krw_balance: float,
        coin_ratio: float,
        realized_daily_pnl: float,
        active_positions: int,
    ) -> bool:
        """주문 가능 여부 반환

        Args:
            krw_balance: 현재 보유 현금(KRW)
            coin_ratio: (코인 평가금액 / 전체 자산) 비율
            realized_daily_pnl: 당일 누적 실현 손익(음수는 손실)
            active_positions: 열려있는 포지션 수
        """

        # 날짜가 바뀌면(자정 지나면) 리셋 – RiskManager 내부 상태 유지 시 대비
        from datetime import datetime

        today = datetime.utcnow().strftime("%Y-%m-%d")
        if self._last_reset_date != today:
            # 현재 버전에서는 RiskManager가 자체 카운터는 없지만, 향후 확장 대비
            self._last_reset_date = today

        # 설정값 로드 (순환 import 방지 – 함수 내부에서 import)
        from config.risk_config import DAILY_LOSS_LIMIT_KRW, MAX_COIN_RATIO
        from config.strategy_config import MAX_CONCURRENT_POSITIONS

        # 1) 일일 손실 한도
        if realized_daily_pnl <= -DAILY_LOSS_LIMIT_KRW:
            return False

        # 2) 자산 비중 한도
        if coin_ratio >= MAX_COIN_RATIO:
            return False

        # 3) 최대 동시 포지션 수
        if active_positions >= MAX_CONCURRENT_POSITIONS:
            return False

        # 4-1) 업비트 최소 주문 금액(5,000 KRW) 체크
        if krw_balance < 5_000:
            return False

        # 4-2) 종목별 최소 주문 단위 – max_position_krw 의 10% 미만이면 스킵
        if krw_balance < self.max_position_krw * 0.1:
            return False

        return True 