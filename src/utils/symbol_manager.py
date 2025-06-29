from __future__ import annotations

"""SymbolManager – 24시간마다 혹은 사용자 정의 주기로 종목 리스트를 동적으로 재선정한다.

현재 버전은 Upbit 원화마켓의 24h 누적 거래금액 상위 N개 심볼을 선택한다.
향후 기준(변동성, 시총 등)을 추가하고 싶다면 `select_symbols` 메서드를 확장하면 된다.
"""

from typing import List, Optional, Dict, Set
import time
from threading import Lock

import requests  # Upbit REST API 호출용

from src.utils.logger import get_logger
from config.settings import TOP_N_SYMBOLS, SAFETY_FILTERS

logger = get_logger(__name__)


class SymbolManager:  # pylint: disable=too-few-public-methods
    """종목 리스트를 주기적으로 재평가·관리한다.

    Args:
        initial_symbols (list[str]): 최초 심볼 리스트 (fallback)
        refresh_interval (int): 재평가 주기(초)
        max_symbols (int): 유지할 최대 종목 수
        buyable_symbols (Optional[Dict[str, bool]]): IndicatorWorker 가 업데이트하는 공유 dict.
            제공 시 안전 필터 통과 & buyable 에 포함된 종목만 후보군으로 사용한다.
    """

    def __init__(
        self,
        initial_symbols: List[str],
        refresh_interval: int = 600,
        max_symbols: int = TOP_N_SYMBOLS,
        buyable_symbols: Optional[Dict[str, bool]] = None,
    ):

        self._symbols: List[str] = initial_symbols.copy()
        self._last_refresh = 0.0
        self.refresh_interval = refresh_interval  # 초
        self.max_symbols = max_symbols
        self._lock = Lock()

        # buyable dict (Manager dict) – key 만 사용
        self._buyable_symbols = buyable_symbols

        # 안전 티커 캐시
        self._safe_tickers: Set[str] | None = None
        self._safe_cache_ts: float = 0.0

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
    def _fetch_safe_tickers(self) -> Set[str]:
        """/market/all 을 호출하여 안전한 KRW 마켓 리스트 반환 (1h 캐시)"""
        now = time.time()
        if self._safe_tickers is not None and (now - self._safe_cache_ts) < 3600:
            return self._safe_tickers

        url_all = "https://api.upbit.com/v1/market/all"
        try:
            resp = requests.get(url_all, params={"is_details": "true"}, timeout=5)
            resp.raise_for_status()
            markets: list[dict] = resp.json()
        except Exception as exc:
            raise RuntimeError(f"Failed to fetch market list: {exc}") from exc

        safe: Set[str] = set()
        for m in markets:
            if not m["market"].startswith("KRW-"):
                continue

            event = m.get("market_event", {})
            warning = bool(event.get("warning"))
            caution = event.get("caution", {}) or {}
            small_acc = bool(caution.get("CONCENTRATION_OF_SMALL_ACCOUNTS"))

            if SAFETY_FILTERS.get("exclude_warning") and warning:
                continue
            if SAFETY_FILTERS.get("exclude_small_acc") and small_acc:
                continue

            safe.add(m["market"])

        if not safe:
            raise RuntimeError("No safe KRW tickers after filtering")

        self._safe_tickers = safe
        self._safe_cache_ts = now
        return safe

    def _select_symbols(self) -> List[str]:
        """안전 필터 + IndicatorWorker 의 buyable 세트 + 거래대금 랭킹"""

        safe_tickers = self._fetch_safe_tickers()

        # buyable 심볼과 교집합 적용
        if self._buyable_symbols is not None and len(self._buyable_symbols) > 0:
            candidates = list(set(self._buyable_symbols.keys()) & safe_tickers)
        else:
            candidates = list(safe_tickers)

        if not candidates:
            logger.warning("No candidates after applying buyable filter; fallback to safe tickers top-volume ranking")
            candidates = list(safe_tickers)

        # 2) 대량 /ticker REST 호출로 24h 거래대금 취득 ----------------------
        results: list[dict] = []
        chunk_size = 100
        for i in range(0, len(candidates), chunk_size):
            markets_chunk = candidates[i : i + chunk_size]
            url_ticker = "https://api.upbit.com/v1/ticker"
            try:
                resp = requests.get(url_ticker, params={"markets": ",".join(markets_chunk)}, timeout=5)
                resp.raise_for_status()
                results.extend(resp.json())
            except Exception as exc:
                logger.warning("Ticker batch request failed (%s-%s): %s", i, i+chunk_size, exc)

        if not results:
            raise RuntimeError("Failed to retrieve ticker information via REST")

        # 3) 거래대금 정렬 및 상위 max_symbols 반환 ---------------------------
        results.sort(key=lambda d: d.get("acc_trade_price_24h", 0.0), reverse=True)

        top_symbols: list[str] = [d["market"] for d in results[: self.max_symbols]]

        if not top_symbols:
            raise RuntimeError("Failed to extract top symbols from ticker data")

        return top_symbols 