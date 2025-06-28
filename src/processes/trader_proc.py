from __future__ import annotations

from multiprocessing import Event, Queue

from src.trading.trader import Trader
from src.utils.logger import get_logger

logger = get_logger(__name__)


def trader_process(
    tick_q: Queue,
    command_q: Queue,
    notify_q: Queue,
    db_q: Queue,
    order_q: Queue,
    resp_q: Queue,
    shutdown_ev: Event,
):
    """Trader.run 을 별도 프로세스로 래핑"""

    logger.info("Trader 프로세스 시작")
    try:
        Trader.run(tick_q, command_q, notify_q, db_q, order_q, resp_q, shutdown_ev)
    except Exception as exc:  # pragma: no cover
        logger.exception("Trader 프로세스 예외: %s", exc)
    finally:
        logger.info("Trader 프로세스 종료") 