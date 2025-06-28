from __future__ import annotations
from queue import Queue, Empty
from threading import Event
import time
from datetime import datetime
import uuid

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
        order_q: Queue,
        resp_q: Queue,
        stop_event: Event,
    ) -> None:
        strategy = ScalpingStrategy()
        risk_mgr = RiskManager(MAX_POSITION_KRW)

        last_order_ts = 0.0
        pending_requests = {}  # {request_id: request_info}
        
        # 초기 잔고 조회
        balance_req_id = str(uuid.uuid4())
        order_q.put({
            "type": "query",
            "method": "get_balance",
            "params": {"ticker": "KRW"},
            "request_id": balance_req_id
        })
        pending_requests[balance_req_id] = {"type": "balance_krw"}

        krw_balance = 0.0
        coin_balance = 0.0

        while not stop_event.is_set():
            # 명령 큐 처리 (pause/resume 등 확장 가능)
            try:
                cmd = command_q.get_nowait()
                logger.info(f"command received: {cmd}")
                # TODO: command 처리 로직
            except Empty:
                pass

            # API 응답 처리
            while not resp_q.empty():
                try:
                    response = resp_q.get_nowait()
                    req_id = response.get("request_id")
                    if req_id in pending_requests:
                        req_info = pending_requests.pop(req_id)
                        if req_info["type"] == "balance_krw":
                            krw_balance = response.get("result", 0.0)
                            logger.debug(f"KRW 잔고 업데이트: {krw_balance}")
                        elif req_info["type"] == "balance_coin":
                            coin_balance = response.get("result", 0.0)
                            logger.debug(f"{SYMBOL} 잔고 업데이트: {coin_balance}")
                        elif req_info["type"] == "buy_order":
                            if "uuid" in response:
                                strategy.entry_price = req_info["price"]
                                notify_q.put(f"[BUY] {SYMBOL} @ {req_info['price']} (주문ID: {response['uuid'][:8]})")
                                db_q.put((datetime.utcnow().isoformat(), "BUY", req_info["price"], req_info["volume"]))
                                # 매수 후 코인 잔고 재조회
                                coin_req_id = str(uuid.uuid4())
                                order_q.put({
                                    "type": "query",
                                    "method": "get_balance",
                                    "params": {"ticker": SYMBOL},
                                    "request_id": coin_req_id
                                })
                                pending_requests[coin_req_id] = {"type": "balance_coin"}
                            else:
                                notify_q.put(f"[BUY ERROR] {response}")
                        elif req_info["type"] == "sell_order":
                            if "uuid" in response:
                                notify_q.put(f"[SELL] {SYMBOL} @ {req_info['price']} (주문ID: {response['uuid'][:8]})")
                                db_q.put((datetime.utcnow().isoformat(), "SELL", req_info["price"], req_info["volume"]))
                                strategy.entry_price = None
                                # 매도 후 KRW 잔고 재조회
                                balance_req_id = str(uuid.uuid4())
                                order_q.put({
                                    "type": "query",
                                    "method": "get_balance",
                                    "params": {"ticker": "KRW"},
                                    "request_id": balance_req_id
                                })
                                pending_requests[balance_req_id] = {"type": "balance_krw"}
                            else:
                                notify_q.put(f"[SELL ERROR] {response}")
                except Exception as exc:
                    logger.exception("응답 처리 오류: %s", exc)

            # 시장 데이터 처리
            try:
                tick = market_q.get(timeout=1)
            except Empty:
                continue

            try:
                current_price = tick["trade_price"]
                
                # 1) 매수 체크
                if strategy.should_buy(tick):
                    if risk_mgr.allow_order(krw_balance):
                        if time.time() - last_order_ts < Trader.ORDER_INTERVAL:
                            continue  # rate-limit
                        
                        vol_krw = min(krw_balance, MAX_POSITION_KRW)
                        if vol_krw < 5000:  # 업비트 최소 주문 금액
                            continue
                            
                        buy_req_id = str(uuid.uuid4())
                        order_q.put({
                            "type": "order",
                            "params": {
                                "market": SYMBOL,
                                "side": "buy",
                                "ord_type": "market",
                                "volume": vol_krw
                            },
                            "request_id": buy_req_id
                        })
                        pending_requests[buy_req_id] = {
                            "type": "buy_order",
                            "price": current_price,
                            "volume": vol_krw
                        }
                        last_order_ts = time.time()

                # 2) 매도 체크
                elif strategy.should_sell(tick):
                    if coin_balance > 0 and time.time() - last_order_ts >= Trader.ORDER_INTERVAL:
                        sell_req_id = str(uuid.uuid4())
                        order_q.put({
                            "type": "order",
                            "params": {
                                "market": SYMBOL,
                                "side": "sell",
                                "ord_type": "market",
                                "volume": coin_balance
                            },
                            "request_id": sell_req_id
                        })
                        pending_requests[sell_req_id] = {
                            "type": "sell_order",
                            "price": current_price,
                            "volume": coin_balance
                        }
                        last_order_ts = time.time()

            except Exception as exc:
                logger.exception("Trading error: %s", exc)
                notify_q.put(f"[ERROR] {exc}")

            # CPU cool-down
            time.sleep(0.01) 