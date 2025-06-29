from __future__ import annotations

"""SymbolManager – 24시간마다 혹은 사용자 정의 주기로 종목 리스트를 동적으로 재선정한다.

현재 버전은 Upbit 원화마켓의 24h 누적 거래금액 상위 N개 심볼을 선택한다.
향후 기준(변동성, 시총 등)을 추가하고 싶다면 `select_symbols` 메서드를 확장하면 된다.
"""

from typing import List
import time
from threading import Lock

import pyupbit  # Upbit REST wrapper – requirements.txt 에 이미 포함돼 있음

from src.utils.logger import get_logger

logger = get_logger(__name__)


class SymbolManager:  # pylint: disable=too-few-public-methods
    """종목 리스트를 주기적으로 재평가·관리한다."""

    def __init__(self, initial_symbols: List[str], refresh_interval: int = 600, max_symbols: int = 3):
        self._symbols: List[str] = initial_symbols.copy()
        self._last_refresh = 0.0
        self.refresh_interval = refresh_interval  # 초
        self.max_symbols = max_symbols
        self._lock = Lock()

    # ----------------------- Public API ----------------------- #
    @property
    def symbols(self) -> List[str]:  # noqa: D401 – simple wrapper
        """현재 활성 종목 리스트 (thread-safe)"""
        with self._lock:
            return self._symbols.copy()

    def maybe_refresh(self) -> bool:
        """필요 시 심볼 리스트를 갱신한다.

        Returns:
            bool: 심볼 리스트가 변경되었는지 여부
        """
        now = time.time()
        if now - self._last_refresh < self.refresh_interval:
            return False

        try:
            new_syms = self._select_symbols()
        except Exception as exc:  # pragma: no cover – API 오류 등 무시하고 유지
            logger.warning("Symbol selection failed: %s", exc)
            self._last_refresh = now
            return False

        with self._lock:
            if set(new_syms) != set(self._symbols):
                logger.info("[SymbolManager] Symbols updated: %s → %s", self._symbols, new_syms)
                self._symbols = new_syms
                self._last_refresh = now
                return True

        self._last_refresh = now
        return False

    # ----------------------- Internal ----------------------- #
    def _select_symbols(self) -> List[str]:
        """Upbit 시세 API를 호출해 24h 거래금액 상위 max_symbols 개를 반환한다."""
        tickers = pyupbit.get_tickers(fiat="KRW")
        if not tickers:
            raise RuntimeError("No KRW tickers returned from Upbit API")

        market_data = pyupbit.get_ticker(tickers)
        # `market_data` 는 list[dict] with keys: market, acc_trade_price_24h 등
        # 정렬하여 상위 N개 선택
        market_data.sort(key=lambda d: d.get("acc_trade_price_24h", 0.0), reverse=True)
        top = [d["market"] for d in market_data[: self.max_symbols]]
        return top 