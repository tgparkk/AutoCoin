from __future__ import annotations

"""SymbolManager – 24시간마다 혹은 사용자 정의 주기로 종목 리스트를 동적으로 재선정한다.

현재 버전은 Upbit 원화마켓의 24h 누적 거래금액 상위 N개 심볼을 선택한다.
향후 기준(변동성, 시총 등)을 추가하고 싶다면 `select_symbols` 메서드를 확장하면 된다.
"""

from typing import List
import time
from threading import Lock

import requests  # Upbit REST API 호출용

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
        """Upbit WebSocket 스냅샷을 이용해 24h 거래대금 상위 심볼을 산출한다."""
        import json
        from websocket import create_connection  # websocket-client

        # Upbit 종목 코드 조회는 공식 REST 엔드포인트만 지원된다.
        url = "https://api.upbit.com/v1/market/all"
        try:
            resp = requests.get(url, timeout=5)
            resp.raise_for_status()
            markets = resp.json()
            tickers = [m["market"] for m in markets if m["market"].startswith("KRW-")]
        except Exception as exc:
            raise RuntimeError(f"Failed to fetch KRW tickers: {exc}") from exc

        if not tickers:
            raise RuntimeError("No KRW tickers returned from Upbit REST API")

        results: list[dict] = []
        chunk_size = 100  # 웹소켓 codes 필드도 100개 이내가 안전

        for i in range(0, len(tickers), chunk_size):
            codes = tickers[i : i + chunk_size]
            try:
                ws = create_connection("wss://api.upbit.com/websocket/v1", timeout=5)
                req_msg = [
                    {"ticket": "symbol_manager"},
                    {"type": "ticker", "codes": codes, "is_only_snapshot": True},
                    {"format": "DEFAULT"},
                ]
                ws.send(json.dumps(req_msg))

                for _ in codes:
                    raw = ws.recv()
                    # 응답은 bytes 형식
                    if isinstance(raw, bytes):
                        data = json.loads(raw.decode("utf-8"))
                    else:
                        data = json.loads(raw)
                    results.append(data)
            except Exception as exc:
                logger.warning("WebSocket snapshot error (%s-%s): %s", i, i+chunk_size, exc)
            finally:
                try:
                    ws.close()
                except Exception:  # pragma: no cover
                    pass

        if not results:
            raise RuntimeError("Failed to retrieve ticker snapshot via WebSocket")

        # 정렬 후 상위 심볼 추출
        results.sort(key=lambda d: d.get("acc_trade_price_24h", 0.0), reverse=True)
        
        # WebSocket 응답 구조 디버깅 및 안전한 파싱
        top = []
        for i, d in enumerate(results[: self.max_symbols]):
            if "cd" in d:
                top.append(d["cd"])
            elif "code" in d:
                top.append(d["code"])
            else:
                logger.warning("Unexpected ticker response format at index %d: %s", i, list(d.keys())[:5])
                # 기본값으로 market 필드 시도
                if "market" in d:
                    top.append(d["market"])
        
        if not top:
            logger.error("No valid symbols extracted from WebSocket responses")
            # 응답 샘플 로깅 (디버깅용)
            if results:
                logger.error("Sample response keys: %s", list(results[0].keys()))
            raise RuntimeError("Failed to extract symbols from ticker data")
            
        return top 