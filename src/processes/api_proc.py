from __future__ import annotations

import time
from multiprocessing import Event, Queue

from src.api.upbit_api import UpbitAPI
from src.utils.errors import UpbitAPIError
from src.utils.logger import get_logger

logger = get_logger(__name__)


def api_process(order_q: Queue, resp_q: Queue, notify_q: Queue, shutdown_ev: Event) -> None:  # pragma: no cover
    """주문/조회 요청을 받아 Upbit API 를 호출하는 별도 프로세스"""

    try:
        api = UpbitAPI()
    except UpbitAPIError as exc:
        logger.error("Upbit API 초기화 실패: %s", exc)
        notify_q.put(f"API Init Error: {exc}")
        shutdown_ev.set()
        return

    logger.info("API 프로세스 시작")

    while not shutdown_ev.is_set():
        try:
            req = order_q.get(timeout=0.5)
        except Exception:
            continue

        request_id = req.get("request_id")
        
        try:
            r_type = req.get("type", "order")
            if r_type == "order":
                res = api.place_order(**req["params"])
                # 주문 응답에 request_id 추가
                if isinstance(res, dict):
                    res["request_id"] = request_id
                resp_q.put(res)
            elif r_type == "query":
                method = getattr(api, req["method"])
                result = method(**req.get("params", {}))
                # 조회 응답을 표준 형식으로 래핑
                response = {
                    "request_id": request_id,
                    "result": result,
                    "method": req["method"]
                }
                resp_q.put(response)
            else:
                raise ValueError(f"Unknown request type: {r_type}")

        except UpbitAPIError as exc:
            logger.warning("API Error: %s", exc)
            notify_q.put(f"API Error: {exc}")
            # 에러 응답도 request_id와 함께 전송
            if request_id:
                error_response = {
                    "request_id": request_id,
                    "error": str(exc),
                    "success": False
                }
                resp_q.put(error_response)
        except Exception as exc:  # pragma: no cover
            logger.exception("API 프로세스 예외: %s", exc)
            notify_q.put(f"API Unknown Error: {exc}")
            # 예외 응답도 request_id와 함께 전송
            if request_id:
                error_response = {
                    "request_id": request_id,
                    "error": str(exc),
                    "success": False
                }
                resp_q.put(error_response)

    logger.info("API 프로세스 종료") 