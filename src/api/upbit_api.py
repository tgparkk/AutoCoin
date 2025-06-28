from __future__ import annotations
import pyupbit

from config.api_config import UPBIT_ACCESS_KEY, UPBIT_SECRET_KEY

from typing import Any, List, Dict, Optional

from src.utils.errors import UpbitAPIError
from src.utils.rate_limiter import rate_limit


class UpbitAPI:
    """업비트 REST API 래퍼

    pyupbit.Upbit 의 기능을 대부분 위임하되, 프로젝트에서 일관된 예외 타입을 사용할 수 있도록
    UpbitAPIError 로 래핑한다. 동기 방식으로만 제공한다.
    """

    def __init__(self) -> None:
        try:
            self._client = pyupbit.Upbit(UPBIT_ACCESS_KEY, UPBIT_SECRET_KEY)
        except Exception as exc:  # pragma: no cover
            raise UpbitAPIError("Upbit 인증 실패: 키를 확인하세요") from exc

    # ----------------------------- 계좌 ----------------------------- #
    @rate_limit(endpoint='account')
    def list_accounts(self) -> List[Dict[str, Any]]:
        try:
            return self._client.get_balances()
        except Exception as exc:
            raise UpbitAPIError(str(exc)) from exc

    @rate_limit(endpoint='account')
    def get_order_chance(self, market: str) -> Dict[str, Any]:
        try:
            return self._client.get_chance(market)
        except Exception as exc:
            raise UpbitAPIError(str(exc)) from exc

    # ----------------------------- 주문 ----------------------------- #
    @rate_limit(endpoint='order')
    def get_order(self, uuid: Optional[str] = None, identifier: Optional[str] = None):
        try:
            return self._client.get_order(uuid=uuid, identifier=identifier)
        except Exception as exc:
            raise UpbitAPIError(str(exc)) from exc

    @rate_limit(endpoint='order')
    def list_orders(
        self,
        state: str = "wait",
        page: int = 1,
        order_by: str = "desc",
        **kwargs,
    ) -> List[Dict[str, Any]]:
        """대기·체결 주문 리스트 조회

        parameters 는 업비트 공식 문서와 동일하게 전달한다.
        """
        try:
            return self._client.get_order_list(state=state, page=page, order_by=order_by, **kwargs)
        except Exception as exc:
            raise UpbitAPIError(str(exc)) from exc

    @rate_limit(endpoint='order')
    def place_order(
        self,
        market: str,
        side: str,
        ord_type: str,
        volume: Optional[float] = None,
        price: Optional[float] = None,
        identifier: Optional[str] = None,
    ) -> Dict[str, Any]:
        """주문 실행

        • market: 예) "KRW-BTC"
        • side: "buy" | "sell"
        • ord_type: "market" | "limit"
        • volume: 수량 (시장가 매수 시 None)
        • price: 가격 (시장가 매도 시 None)
        """
        try:
            if side == "buy" and ord_type == "market":
                assert price is None and volume is not None, "시장가 매수는 KRW 금액(volume) 필요"
                return self._client.buy_market_order(market, volume)
            if side == "sell" and ord_type == "market":
                assert volume is not None, "시장가 매도는 코인 수량(volume) 필요"
                return self._client.sell_market_order(market, volume)
            if side == "buy" and ord_type == "limit":
                assert price is not None and volume is not None, "지정가 매수는 수량·가격 필요"
                return self._client.buy_limit_order(market, price, volume)
            if side == "sell" and ord_type == "limit":
                assert price is not None and volume is not None, "지정가 매도는 수량·가격 필요"
                return self._client.sell_limit_order(market, price, volume)
            raise ValueError("지원하지 않는 주문 방식")
        except Exception as exc:
            raise UpbitAPIError(str(exc)) from exc

    @rate_limit(endpoint='cancel')
    def cancel_order(self, uuid: Optional[str] = None, identifier: Optional[str] = None):
        try:
            return self._client.cancel_order(uuid=uuid, identifier=identifier)
        except Exception as exc:
            raise UpbitAPIError(str(exc)) from exc

    def cancel_orders(self, uuids: List[str]):
        results: List[Dict[str, Any]] = []
        for uid in uuids:
            try:
                results.append(self.cancel_order(uuid=uid))
            except UpbitAPIError as exc:  # pragma: no cover – 개별 실패 무시하고 계속
                results.append({"uuid": uid, "error": str(exc)})
        return results

    # ----------------------------- 시세 ----------------------------- #
    @rate_limit(endpoint='market')
    def get_markets(self, is_details: bool = False):
        try:
            # pyupbit 은 show_details 플래그 사용
            return pyupbit.get_tickers(fiat="ALL", verbose=is_details)
        except Exception as exc:
            raise UpbitAPIError(str(exc)) from exc

    @rate_limit(endpoint='market')
    def get_candles(
        self,
        unit: str,
        market: str,
        count: int = 200,
        to: Optional[str] = None,
    ):
        """초/분/일 캔들 통합 호출

        unit 예)
        • "sec60"  → 60초
        • "min1"   → 1분
        • "day"    → 일봉
        """
        try:
            interval_map = {
                "sec1": "minute1",
                "sec30": "minute30",
                "sec60": "minute60",
                "min1": "minute1",
                "min3": "minute3",
                "min5": "minute5",
                "min15": "minute15",
                "min30": "minute30",
                "min60": "minute60",
                "min240": "minute240",
                "day": "day",
            }
            interval = interval_map.get(unit, unit)
            return pyupbit.get_ohlcv(market, interval=interval, count=count, to=to)
        except Exception as exc:
            raise UpbitAPIError(str(exc)) from exc

    @rate_limit(endpoint='market')
    def get_trades(self, market: str, count: int = 30):
        try:
            return pyupbit.get_ticks(market, count=count)
        except Exception as exc:
            raise UpbitAPIError(str(exc)) from exc

    @rate_limit(endpoint='market')
    def get_ticker(self, markets: List[str]):
        try:
            return pyupbit.get_current_price(markets)
        except Exception as exc:
            raise UpbitAPIError(str(exc)) from exc

    # ----------------- 기존 메서드 호환 ----------------- #
    @rate_limit(endpoint='account')
    def get_balance(self, ticker: str = "KRW") -> float:  # noqa: D401 – simple wrapper
        return self._client.get_balance(ticker)

    def buy_market(self, ticker: str, krw_amount: float):
        return self.place_order(ticker, side="buy", ord_type="market", volume=krw_amount)

    def sell_market(self, ticker: str, volume: float):
        return self.place_order(ticker, side="sell", ord_type="market", volume=volume) 