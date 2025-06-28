from __future__ import annotations
from queue import Queue, Empty
from threading import Event
import time
from datetime import datetime
import uuid
from typing import Dict, Any, Optional

from src.strategy.strategy_manager import StrategyManager
from src.strategy.base_strategy import OrderFill
from src.trading.risk_manager import RiskManager
from config.strategy_config import SYMBOLS, get_max_position_krw
from src.utils.logger import get_logger

logger = get_logger(__name__)


class Trader:
    """실시간 데이터로 다중 종목 전략 실행 및 주문"""

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
        strategy_name: str = "scalping"
    ) -> None:
        
        # 전략 매니저 초기화
        strategy_manager = StrategyManager(strategy_name)
        if not strategy_manager.prepare_all_strategies():
            logger.error("전략 초기화 실패")
            return
        
        # 리스크 매니저 (종목별로 관리)
        risk_managers = {
            symbol: RiskManager(get_max_position_krw(symbol)) 
            for symbol in SYMBOLS
        }

        last_order_ts = 0.0
        trading_paused = False  # /pause 명령 처리용
        pending_requests = {}  # {request_id: request_info}
        
        # 종목별 잔고 관리
        krw_balance = 0.0  # 현금 잔고
        coin_balances = {symbol: 0.0 for symbol in SYMBOLS}  # 보유 코인 수량
        # 코인별 최근 가격 저장 (자산 비중 계산용)
        last_prices = {symbol: 0.0 for symbol in SYMBOLS}
        
        # 초기 잔고 조회
        balance_req_id = str(uuid.uuid4())
        order_q.put({
            "type": "query",
            "method": "get_balance",
            "params": {"ticker": "KRW"},
            "request_id": balance_req_id
        })
        pending_requests[balance_req_id] = {"type": "balance_krw"}
        
        # 각 종목별 코인 잔고 조회
        for symbol in SYMBOLS:
            coin_req_id = str(uuid.uuid4())
            order_q.put({
                "type": "query",
                "method": "get_balance",
                "params": {"ticker": symbol},
                "request_id": coin_req_id
            })
            pending_requests[coin_req_id] = {"type": "balance_coin", "symbol": symbol}

        logger.info("Trader 시작: 전략=%s, 종목=%s", strategy_name, SYMBOLS)

        while not stop_event.is_set():
            # 명령 큐 처리
            try:
                cmd = command_q.get_nowait()
                logger.info("Command received: %s", cmd)
                
                cmd_type = cmd.get("type")
                # ---------------- Command Handling ----------------
                if cmd_type == "portfolio_status":
                    status = strategy_manager.get_portfolio_status()
                    notify_q.put(f"[PORTFOLIO] {status}")
                elif cmd_type == "strategy_performance":
                    performance = strategy_manager.get_strategy_performance()
                    notify_q.put(f"[PERFORMANCE] {performance}")
                elif cmd_type == "pause":
                    trading_paused = True
                    notify_q.put("[INFO] Trading paused ⏸")
                elif cmd_type == "resume":
                    trading_paused = False
                    notify_q.put("[INFO] Trading resumed ▶️")
                elif cmd_type == "shutdown":
                    stop_event.set()
                    notify_q.put("[INFO] Shutdown signal received 📴")
                    
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
                            logger.debug("KRW 잔고 업데이트: %s", krw_balance)
                            
                        elif req_info["type"] == "balance_coin":
                            symbol = req_info["symbol"]
                            coin_balances[symbol] = response.get("result", 0.0)
                            logger.debug("%s 잔고 업데이트: %s", symbol, coin_balances[symbol])
                            
                        elif req_info["type"] == "buy_order":
                            symbol = req_info["symbol"]
                            if "uuid" in response:
                                # 주문 체결 정보를 전략에 전달
                                fill = OrderFill(
                                    symbol=symbol,
                                    side="buy",
                                    price=req_info["price"],
                                    volume=req_info["volume"],
                                    timestamp=time.time(),
                                    order_id=response["uuid"]
                                )
                                strategy_manager.process_order_fill(symbol, fill)
                                
                                notify_q.put(f"[BUY] {symbol} @ {req_info['price']} (ID: {response['uuid'][:8]})")
                                db_q.put((datetime.utcnow().isoformat(), "BUY", symbol, req_info["price"], req_info["volume"]))
                                
                                # 잔고 재조회
                                _refresh_balances(order_q, pending_requests, symbol)
                            else:
                                notify_q.put(f"[BUY ERROR] {symbol}: {response}")
                                
                        elif req_info["type"] == "sell_order":
                            symbol = req_info["symbol"]
                            if "uuid" in response:
                                # 주문 체결 정보를 전략에 전달
                                fill = OrderFill(
                                    symbol=symbol,
                                    side="sell",
                                    price=req_info["price"],
                                    volume=req_info["volume"],
                                    timestamp=time.time(),
                                    order_id=response["uuid"]
                                )
                                strategy_manager.process_order_fill(symbol, fill)
                                
                                notify_q.put(f"[SELL] {symbol} @ {req_info['price']} (ID: {response['uuid'][:8]})")
                                db_q.put((datetime.utcnow().isoformat(), "SELL", symbol, req_info["price"], req_info["volume"]))
                                
                                # 잔고 재조회
                                _refresh_balances(order_q, pending_requests, symbol)
                            else:
                                notify_q.put(f"[SELL ERROR] {symbol}: {response}")
                                
                except Exception as exc:
                    logger.exception("응답 처리 오류: %s", exc)

            # 매매 일시정지 시 시장 데이터 무시 (명령/응답 처리는 계속 진행)
            if trading_paused:
                time.sleep(0.1)
                continue

            # 시장 데이터 처리
            try:
                tick = market_q.get(timeout=1)
                symbol = tick.get("code") or tick.get("market")
                
                if not symbol or symbol not in SYMBOLS:
                    continue
                    
            except Empty:
                continue

            try:
                current_price = tick["trade_price"]
                # 최근 가격 저장 (자산 비중 계산용)
                last_prices[symbol] = current_price
                
                # 전략 실행
                signal = strategy_manager.process_tick(symbol, tick)
                if not signal or signal.get("action") == "none":
                    continue
                
                action = signal["action"]
                reason = signal.get("reason", "")
                
                # Rate limiting 체크
                if time.time() - last_order_ts < Trader.ORDER_INTERVAL:
                    continue
                
                # 매수 처리
                if action == "buy":
                    risk_mgr = risk_managers[symbol]

                    # -------------------- Risk / Money Management --------------------
                    # 1) 자산 비중 계산
                    total_coin_value = sum(
                        coin_balances[sym] * last_prices.get(sym, 0.0)
                        for sym in SYMBOLS
                    )
                    total_assets = total_coin_value + krw_balance
                    coin_ratio = (total_coin_value / total_assets) if total_assets > 0 else 0.0

                    # 2) 당일 실현 손익 합계 (모든 전략 합산)
                    realized_daily_pnl = sum(
                        s.total_pnl for s in strategy_manager.strategies.values()
                    )

                    if risk_mgr.allow_order(
                        krw_balance=krw_balance,
                        coin_ratio=coin_ratio,
                        realized_daily_pnl=realized_daily_pnl,
                        active_positions=strategy_manager.active_positions,
                    ):
                        max_krw = get_max_position_krw(symbol)
                        vol_krw = min(krw_balance, max_krw)
                        
                        if vol_krw < 5000:  # 업비트 최소 주문 금액
                            continue
                            
                        buy_req_id = str(uuid.uuid4())
                        order_q.put({
                            "type": "order",
                            "params": {
                                "market": symbol,
                                "side": "buy",
                                "ord_type": "market",
                                "volume": vol_krw
                            },
                            "request_id": buy_req_id
                        })
                        pending_requests[buy_req_id] = {
                            "type": "buy_order",
                            "symbol": symbol,
                            "price": current_price,
                            "volume": vol_krw / current_price,  # 코인 수량 계산
                            "reason": reason
                        }
                        last_order_ts = time.time()
                        logger.info("매수 주문: %s @ %s (%s)", symbol, current_price, reason)

                # 매도 처리
                elif action == "sell":
                    coin_balance = coin_balances.get(symbol, 0.0)
                    sell_volume = signal.get("volume", coin_balance)  # 부분 청산 지원
                    
                    if sell_volume > 0:
                        sell_req_id = str(uuid.uuid4())
                        order_q.put({
                            "type": "order",
                            "params": {
                                "market": symbol,
                                "side": "sell",
                                "ord_type": "market",
                                "volume": sell_volume
                            },
                            "request_id": sell_req_id
                        })
                        pending_requests[sell_req_id] = {
                            "type": "sell_order",
                            "symbol": symbol,
                            "price": current_price,
                            "volume": sell_volume,
                            "reason": reason
                        }
                        last_order_ts = time.time()
                        logger.info("매도 주문: %s @ %s, 수량: %s (%s)", symbol, current_price, sell_volume, reason)

            except Exception as exc:
                logger.exception("Trading error: %s", exc)
                notify_q.put(f"[ERROR] {exc}")

            # CPU cool-down
            time.sleep(0.01)
        
        logger.info("Trader 종료")


def _refresh_balances(order_q: Queue, pending_requests: Dict, symbol: str) -> None:
    """잔고 재조회 요청"""
    # KRW 잔고
    krw_req_id = str(uuid.uuid4())
    order_q.put({
        "type": "query",
        "method": "get_balance",
        "params": {"ticker": "KRW"},
        "request_id": krw_req_id
    })
    pending_requests[krw_req_id] = {"type": "balance_krw"}
    
    # 코인 잔고
    coin_req_id = str(uuid.uuid4())
    order_q.put({
        "type": "query",
        "method": "get_balance",
        "params": {"ticker": symbol},
        "request_id": coin_req_id
    })
    pending_requests[coin_req_id] = {"type": "balance_coin", "symbol": symbol} 