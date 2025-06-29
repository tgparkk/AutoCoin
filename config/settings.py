from __future__ import annotations
import pathlib

# 프로젝트 루트 경로
BASE_DIR = pathlib.Path(__file__).resolve().parent.parent

# 로그 디렉터리 생성
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

# WebSocket 설정
# 주문book(channel) 도 함께 구독하도록 기본값을 확장
WEBSOCKET_CHANNELS = ["ticker", "orderbook"]  # 필요 시 ["ticker"] 로도 설정 가능
WEBSOCKET_HEARTBEAT_TIMEOUT = 30.0  # 초
WEBSOCKET_MAX_RETRIES = -1  # -1은 무제한
WEBSOCKET_BACKOFF_BASE = 1.0  # 초
WEBSOCKET_MAX_BACKOFF = 32.0  # 초

# -----------------------------------------------------------
# Symbol & Strategy 관련 설정 (IndicatorWorker · SymbolManager)
# -----------------------------------------------------------
# 가격 지표를 기반으로 매수 가능한 종목을 판단할 때 사용할 파라미터
BUY_SIGNAL_PARAMS = {
    # EMA 기간
    "ema_fast": 20,
    "ema_slow": 50,
    # RSI 기간 및 임계값
    "rsi_period": 14,
    "rsi_oversold": 30.0,
}

# Upbit /market/all 필터 단계에서 제외할 조건 (함수로도 확장 가능)
SAFETY_FILTERS = {
    "exclude_warning": True,  # 투자유의 종목 제외
    "exclude_small_acc": True,  # 소액계좌 과다 종목 제외
}

# 심볼 매니저가 유지할 최대 종목 수 (거래대금 랭킹 상위 N)
TOP_N_SYMBOLS = 3

# 심볼 변경 이벤트가 빈번하지 않도록 최소 유지 시간(초)
MIN_SYMBOL_STABLE_SEC = 600  # 10분 