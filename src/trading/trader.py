from __future__ import annotations
from queue import Queue, Empty
from threading import Event
import time
from datetime import datetime

from src.api.upbit_api import UpbitAPI
from src.strategy.scalping_strategy import ScalpingStrategy
from src.trading.risk_manager import RiskManager
from config.strategy_config import SYMBOL, MAX_POSITION_KRW
from src.utils.logger import get_logger

logger = get_logger(__name__)


class Trader:
    """실시간 데이터로 전략 실행 및 주문"""

    ORDER_INTERVAL = 0.15  # 초 (Upbit 1초당 8회 제한)

    @staticmethod
    def run(
        market_q: Queue,
        command_q: Queue,
        notify_q: Queue,
        db_q: Queue,
        stop_event: Event,
    ) -> None:
        api = UpbitAPI()
        strategy = ScalpingStrategy()
        risk_mgr = RiskManager(MAX_POSITION_KRW)

        last_order_ts = 0.0

        while not stop_event.is_set():
            # 명령 큐 처리 (pause/resume 등 확장 가능)
            try:
                cmd = command_q.get_nowait()
                logger.info(f"command received: {cmd}")
                # TODO: command 처리 로직
            except Empty:
                pass

            # 시장 데이터 처리
            try:
                tick = market_q.get(timeout=1)
            except Empty:
                continue

            try:
                # 1) 매수 체크
                if strategy.should_buy(tick):
                    krw_balance = api.get_balance("KRW")
                    if risk_mgr.allow_order(krw_balance):
                        if time.time() - last_order_ts < Trader.ORDER_INTERVAL:
                            continue  # rate-limit
                        vol_krw = min(krw_balance, MAX_POSITION_KRW)
                        api.buy_market(SYMBOL, vol_krw)
                        strategy.entry_price = tick["trade_price"]
                        notify_q.put(f"[BUY] {SYMBOL} @ {strategy.entry_price}")
                        db_q.put((datetime.utcnow().isoformat(), "BUY", strategy.entry_price, vol_krw))
                        last_order_ts = time.time()

                # 2) 매도 체크
                elif strategy.should_sell(tick):
                    coin_balance = api.get_balance(SYMBOL)
                    if coin_balance > 0 and time.time() - last_order_ts >= Trader.ORDER_INTERVAL:
                        api.sell_market(SYMBOL, coin_balance)
                        notify_q.put(f"[SELL] {SYMBOL} @ {tick['trade_price']}")
                        db_q.put((datetime.utcnow().isoformat(), "SELL", tick["trade_price"], coin_balance))
                        strategy.entry_price = None
                        last_order_ts = time.time()

            except Exception as exc:
                logger.exception("Trading error: %s", exc)
                notify_q.put(f"[ERROR] {exc}")

            # CPU cool-down
            time.sleep(0.01) 