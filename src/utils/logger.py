from __future__ import annotations

import logging
from typing import Any


def get_logger(name: str | None = None, level: int = logging.INFO) -> logging.Logger:  # noqa: D401
    """프로젝트 전역에서 사용되는 Logger 반환

    중복 핸들러 등록을 방지하기 위해 동일 이름 로거가 이미 설정되면 그대로 반환한다.
    """

    logger = logging.getLogger(name)

    if not logger.handlers:
        logger.setLevel(level)
        handler: logging.Handler = logging.StreamHandler()
        formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        # 하위 로거가 루트 핸들러를 중복 사용하지 않도록
        logger.propagate = False

    return logger 