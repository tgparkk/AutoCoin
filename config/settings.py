from __future__ import annotations
import pathlib

# 프로젝트 루트 경로
BASE_DIR = pathlib.Path(__file__).resolve().parent.parent

# 로그 디렉터리 생성
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

# WebSocket 설정
WEBSOCKET_CHANNELS = ["ticker"]  # ["ticker", "orderbook"] 중 선택
WEBSOCKET_HEARTBEAT_TIMEOUT = 30.0  # 초
WEBSOCKET_MAX_RETRIES = -1  # -1은 무제한
WEBSOCKET_BACKOFF_BASE = 1.0  # 초
WEBSOCKET_MAX_BACKOFF = 32.0  # 초 