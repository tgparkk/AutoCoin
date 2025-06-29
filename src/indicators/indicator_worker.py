from __future__ import annotations

import time
from collections import defaultdict, deque
from datetime import datetime
from multiprocessing import Event, Queue
from typing import Dict, Deque, List

import numpy as np
import pandas as pd

from config.settings import BUY_SIGNAL_PARAMS
from src.utils.logger import get_logger

logger = get_logger(__name__)

# -------------------------------------------------------------------------------------------------
# Helper functions – EMA, RSI 계산 (pandas 기반)
# -------------------------------------------------------------------------------------------------

def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """상대강도지수(RSI) – pandas 활용"""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    rs = avg_gain / (avg_loss + 1e-9)
    return 100 - (100 / (1 + rs))


class IndicatorWorker:  # pylint: disable=too-few-public-methods
    """실시간 Tick Queue 를 소비하며 매수 가능한 심볼을 판단하여 공유 dict 에 업데이트"""

    MAX_TICKS = 1000  # per-market 버퍼 길이

    def __init__(self, tick_q: Queue, buyable_symbols: Dict[str, bool], shutdown_ev: Event):
        self.tick_q = tick_q
        self.buyable_symbols = buyable_symbols
        self.shutdown_ev = shutdown_ev

        # market ➜ deque[float] (최근 가격 라인)
        self._price_buffers: Dict[str, Deque[float]] = defaultdict(lambda: deque(maxlen=self.MAX_TICKS))

        # 캐시된 buy 여부 (직전 상태)
        self._prev_buyable: Dict[str, bool] = {}

        # 파라미터 로드
        self.ema_fast = BUY_SIGNAL_PARAMS.get("ema_fast", 20)
        self.ema_slow = BUY_SIGNAL_PARAMS.get("ema_slow", 50)
        self.rsi_period = BUY_SIGNAL_PARAMS.get("rsi_period", 14)
        self.rsi_oversold = BUY_SIGNAL_PARAMS.get("rsi_oversold", 30.0)

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def run(self) -> None:  # pragma: no cover – 프로세스 메인 루프
        logger.info("IndicatorWorker 프로세스 시작 – 매수 신호 파라미터=%s", BUY_SIGNAL_PARAMS)
        while not self.shutdown_ev.is_set():
            try:
                tick = self.tick_q.get(timeout=0.5)
            except Exception:
                continue

            market = tick.get("market") or tick.get("code")
            if market is None:
                continue
            price = tick.get("trade_price") or tick.get("price")
            if price is None:
                continue

            self._price_buffers[market].append(float(price))

            # 신호 평가 (충분한 데이터가 있을 때만)
            buf = self._price_buffers[market]
            if len(buf) < max(self.ema_slow, self.rsi_period) + 5:
                continue

            try:
                buyable = self._is_buy_signal(list(buf))
            except Exception as exc:  # pragma: no cover – 방어적
                logger.warning("Buy signal calc error (%s): %s", market, exc)
                continue

            prev_state = self._prev_buyable.get(market)
            if prev_state is None or prev_state != buyable:
                # 상태 변경 시 dict 업데이트
                if buyable:
                    self.buyable_symbols[market] = True  # 값은 의미 없고 key 존재 여부로 사용
                else:
                    self.buyable_symbols.pop(market, None)
                self._prev_buyable[market] = buyable
                logger.debug("[Indicator] %s buyable=%s", market, buyable)

        logger.info("IndicatorWorker 프로세스 종료")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _is_buy_signal(self, prices: List[float]) -> bool:
        """EMA & RSI 기반 매수 조건 판단"""
        ser = pd.Series(prices)
        ema_fast = _ema(ser, self.ema_fast).iloc[-1]
        ema_slow = _ema(ser, self.ema_slow).iloc[-1]
        rsi_val = _rsi(ser, self.rsi_period).iloc[-1]

        return (ema_fast > ema_slow) and (rsi_val < self.rsi_oversold)


# ----------------------------------------------------------------------------------------------
# Process entrypoint wrapper – 다른 프로세스에서 import 없이 사용하기 위함
# ----------------------------------------------------------------------------------------------

def indicator_worker_process(tick_q: Queue, buyable_symbols: Dict[str, bool], shutdown_ev: Event):  # pragma: no cover
    worker = IndicatorWorker(tick_q, buyable_symbols, shutdown_ev)
    worker.run() 