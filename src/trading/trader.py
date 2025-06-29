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
from src.utils.symbol_manager import SymbolManager

logger = get_logger(__name__)


class Trader:
    """실시간 데이터로 다중 종목 전략 실행 및 주문"""

    ORDER_INTERVAL = 0.15  # 초 (Upbit 1초당 8회 제한)

    # ---------------- Pending-order 관리 상수 ----------------
    PENDING_CHECK_INTERVAL = 0.3  # 주문 상태 조회 주기(초)
    PENDING_TIMEOUT_SEC = 10.0     # 미체결 시 자동 취소 시점(초)

    @staticmethod
    def rebind_symbols(
        new_symbols: list[str],
        strategy_manager: StrategyManager,
        risk_managers: Dict[str, RiskManager],
        coin_balances: Dict[str, float],
        last_prices: Dict[str, float],
        order_q: Queue,
        pending_requests: Dict[str, Any],
        notify_q: Queue,
    ) -> None:
        """심볼 변경 시 포지션·리스크 매니저·잔고 구조를 재바인딩한다.

        1. 제거된(sym not in new_symbols) 심볼 중 보유 수량이 있는 경우 시장가 전량 매도 주문
           → 체결 이후 잔고 재조회 로직은 기존 pending_orders 처리부에서 수행된다.
        2. risk_managers / balances / price dict를 업데이트해 신규 심볼을 추가하고 제거 심볼을 뺀다.
        """

        cur_syms = set(risk_managers.keys())
        new_syms_set = set(new_symbols)

        removed_syms = cur_syms - new_syms_set
        added_syms = new_syms_set - cur_syms

        # ---------------- 제거 심볼 처리 ----------------
        for sym in removed_syms:
            vol = coin_balances.get(sym, 0.0)
            if vol and vol > 0:
                sell_req_id = str(uuid.uuid4())
                order_q.put({
                    "type": "order",
                    "params": {
                        "market": sym,
                        "side": "sell",
                        "ord_type": "market",
                        "volume": vol,
                    },
                    "request_id": sell_req_id,
                })
                pending_requests[sell_req_id] = {
                    "type": "sell_order",
                    "symbol": sym,
                    "price": last_prices.get(sym, 0.0),
                    "volume": vol,
                    "reason": "symbol_removed",
                }
                notify_q.put(f"[AUTO SELL] {sym} 제거로 전량 매도 요청")

            # regardless of position, remove from dictionaries to prevent further trading
            risk_managers.pop(sym, None)
            coin_balances.pop(sym, None)
            last_prices.pop(sym, None)

        # ---------------- 추가 심볼 처리 ----------------
        for sym in added_syms:
            risk_managers[sym] = RiskManager(get_max_position_krw(sym))
            coin_balances[sym] = coin_balances.get(sym, 0.0)
            last_prices[sym] = last_prices.get(sym, 0.0)

            # 잔고 조회 (새 심볼 첫 추가)
            bal_req_id = str(uuid.uuid4())
            order_q.put({
                "type": "query",
                "method": "get_balance",
                "params": {"ticker": sym},
                "request_id": bal_req_id,
            })
            pending_requests[bal_req_id] = {"type": "balance_coin", "symbol": sym}

        # StrategyManager 에 심볼 업데이트
        strategy_manager.update_symbols(list(new_syms_set))

        notify_q.put(f"[SYMBOLS] 업데이트 완료 → {sorted(new_syms_set)}")

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
        
        # ---------------- 심볼 매니저 ----------------
        symbol_manager = SymbolManager(SYMBOLS)

        # 리스크 매니저 (종목별로 관리)
        risk_managers = {
            symbol: RiskManager(get_max_position_krw(symbol)) 
            for symbol in symbol_manager.symbols
        }

        last_order_ts = 0.0
        trading_paused = False  # /pause 명령 처리용
        pending_requests = {}  # {request_id: request_info}
        pending_orders = {}    # {uuid: order_info}
        
        # 종목별 잔고 관리
        krw_balance = 0.0  # 현금 잔고
        coin_balances = {symbol: 0.0 for symbol in symbol_manager.symbols}  # 보유 코인 수량
        # 코인별 최근 가격 저장 (자산 비중 계산용)
        last_prices = {symbol: 0.0 for symbol in symbol_manager.symbols}
        
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
        for symbol in symbol_manager.symbols:
            coin_req_id = str(uuid.uuid4())
            order_q.put({
                "type": "query",
                "method": "get_balance",
                "params": {"ticker": symbol},
                "request_id": coin_req_id
            })
            pending_requests[coin_req_id] = {"type": "balance_coin", "symbol": symbol}

        logger.info("Trader 시작: 전략=%s, 종목=%s", strategy_name, symbol_manager.symbols)

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
                                # 주문 접수(미체결) 상태로 등록
                                uuid_val = response["uuid"]
                                pending_orders[uuid_val] = {
                                    "symbol": symbol,
                                    "side": "buy",
                                    "volume": req_info["volume"],
                                    "price": req_info["price"],
                                    "sent_ts": time.time(),
                                    "last_check": 0.0,
                                }
                                notify_q.put(f"[BUY REQUEST] {symbol} 접수 (ID: {uuid_val[:8]})")
                            else:
                                notify_q.put(f"[BUY ERROR] {symbol}: {response}")
                                
                        elif req_info["type"] == "sell_order":
                            symbol = req_info["symbol"]
                            if "uuid" in response:
                                uuid_val = response["uuid"]
                                pending_orders[uuid_val] = {
                                    "symbol": symbol,
                                    "side": "sell",
                                    "volume": req_info["volume"],
                                    "price": req_info["price"],
                                    "sent_ts": time.time(),
                                    "last_check": 0.0,
                                }
                                notify_q.put(f"[SELL REQUEST] {symbol} 접수 (ID: {uuid_val[:8]})")
                            else:
                                notify_q.put(f"[SELL ERROR] {symbol}: {response}")

                        # ---------------- 주문 상태 응답 ----------------
                        elif req_info["type"] == "order_status":
                            uuid_val = req_info["uuid"]
                            po = pending_orders.get(uuid_val)
                            if po is None:
                                continue  # 이미 처리되었을 가능성

                            data = response.get("result", {})
                            state = data.get("state")

                            # 체결 완료
                            if state == "done":
                                try:
                                    total_vol = float(data.get("volume", 0))
                                    remain_vol = float(data.get("remaining_volume", 0))
                                    exec_vol = total_vol - remain_vol if total_vol else po["volume"]
                                except Exception:
                                    exec_vol = po["volume"]

                                # 평균 체결가 계산
                                try:
                                    trades = data.get("trades", [])
                                    if trades:
                                        avg_price = sum(float(t["price"]) * float(t["volume"]) for t in trades) / sum(float(t["volume"]) for t in trades)
                                    else:
                                        avg_price = po["price"]
                                except Exception:
                                    avg_price = po["price"]

                                fill = OrderFill(
                                    symbol=po["symbol"],
                                    side=po["side"],
                                    price=avg_price,
                                    volume=exec_vol,
                                    timestamp=time.time(),
                                    order_id=uuid_val,
                                )
                                strategy_manager.process_order_fill(po["symbol"], fill)

                                notify_q.put(f"[FILL] {po['side'].upper()} {po['symbol']} @ {avg_price:.0f} (ID: {uuid_val[:8]})")
                                db_q.put((datetime.utcnow().isoformat(), po["side"].upper(), po["symbol"], avg_price, exec_vol))

                                # 잔고 재조회
                                _refresh_balances(order_q, pending_requests, po["symbol"])

                                pending_orders.pop(uuid_val, None)

                            # 미체결(cancel 포함)
                            elif state in ("cancel", "fail"):
                                notify_q.put(f"[CANCEL] {po['symbol']} 주문 취소/실패 (ID: {uuid_val[:8]})")
                                pending_orders.pop(uuid_val, None)

                        # ---------------- 주문 취소 응답 ----------------
                        elif req_info["type"] == "cancel_order":
                            uuid_val = req_info["uuid"]
                            pending_orders.pop(uuid_val, None)
                            notify_q.put(f"[CANCELLED] 주문취소 완료 (ID: {uuid_val[:8]})")

                except Exception as exc:
                    logger.exception("응답 처리 오류: %s", exc)

            # 매매 일시정지 시 시장 데이터 무시 (명령/응답 처리는 계속 진행)
            if trading_paused:
                time.sleep(0.1)
                continue

            # -------------------- Pending 주문 상태 조회 --------------------
            now_ts = time.time()
            for uid, po in list(pending_orders.items()):
                # 상태 조회 주기
                if now_ts - po["last_check"] >= Trader.PENDING_CHECK_INTERVAL:
                    status_req_id = str(uuid.uuid4())
                    order_q.put({
                        "type": "query",
                        "method": "get_order",
                        "params": {"uuid": uid},
                        "request_id": status_req_id,
                    })
                    pending_requests[status_req_id] = {"type": "order_status", "uuid": uid}
                    po["last_check"] = now_ts

                # 타임아웃 처리(선택)
                if now_ts - po["sent_ts"] >= Trader.PENDING_TIMEOUT_SEC:
                    cancel_req_id = str(uuid.uuid4())
                    order_q.put({
                        "type": "query",
                        "method": "cancel_order",
                        "params": {"uuid": uid},
                        "request_id": cancel_req_id,
                    })
                    pending_requests[cancel_req_id] = {"type": "cancel_order", "uuid": uid}

            # 시장 데이터 처리
            try:
                tick = market_q.get(timeout=1)
                symbol = tick.get("code") or tick.get("market")
                
                if not symbol or symbol not in symbol_manager.symbols:
                    continue
                    
            except Empty:
                continue

            try:
                current_price = tick.get("trade_price")
                # 최근 가격 저장 (자산 비중 계산용)
                if current_price is not None:
                    last_prices[symbol] = current_price
                
                # 전략 실행 (ticker & orderbook 모두 전달)
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
                    if current_price is None:
                        continue  # 가격 정보 없으면 주문 불가
                    risk_mgr = risk_managers[symbol]

                    # -------------------- Risk / Money Management --------------------
                    # 1) 자산 비중 계산
                    total_coin_value = sum(
                        coin_balances[sym] * last_prices.get(sym, 0.0)
                        for sym in symbol_manager.symbols
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
                    if current_price is None:
                        continue  # 가격 정보 없으면 주문 불가
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

            # ---------------- 심볼 동적 갱신 ----------------
            if symbol_manager.maybe_refresh():
                Trader.rebind_symbols(
                    symbol_manager.symbols,
                    strategy_manager,
                    risk_managers,
                    coin_balances,
                    last_prices,
                    order_q,
                    pending_requests,
                    notify_q,
                )

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