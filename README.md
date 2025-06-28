# AutoCoin

업비트 웹소켓 기반 스캘핑 자동매매 봇

## 주요 기능

### 📡 WebSocket 연결 관리
- **자동 재연결**: 연결 끊김 시 지수 백오프 방식으로 자동 재연결
- **Heartbeat 모니터링**: 30초 이상 데이터 없으면 재연결 시도
- **다중 채널 지원**: ticker, orderbook 채널 선택 가능
- **안정적인 데이터 수신**: 큐 오버플로우 방지 및 예외 처리

### 🚦 API Rate Limiting
- **토큰 버킷 알고리즘**: 업비트 API 제한에 맞춰 자동 조절
- **엔드포인트별 제한**: 주문/취소/계좌/시세 API별 개별 관리
- **자동 대기**: Rate limit 초과 시 자동으로 대기 후 재시도
- **데코레이터 방식**: 간단한 `@rate_limit` 데코레이터로 적용

### 📈 전략(Strategy) 시스템
- **다중 종목 지원**: 여러 암호화폐를 동시에 거래
- **확장된 전략 인터페이스**: 라이프사이클 메서드와 상태 관리
- **다양한 전략**: Scalping, MA Cross, RSI, Advanced Scalping
- **트레일링 스탑**: 수익을 보호하는 동적 손절가
- **부분 청산**: 수익 구간별 단계적 포지션 정리
- **종목별 개별 설정**: 각 암호화폐에 최적화된 파라미터

### ⚙️ 설정 관리
- **채널 선택**: `config/settings.py`에서 WebSocket 채널 설정
- **재연결 옵션**: 최대 재시도 횟수, 백오프 시간 등 세부 조정 가능
- **Rate Limit 커스터마이징**: API별 제한 수치 조정 가능
- **전략별 설정**: `config/strategy_config.py`에서 전략과 종목별 파라미터 관리

## 빠른 시작
```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp config/config.ini.example config/config.ini  # 설정 파일 복사 후 키 입력

# 기본 스캘핑 전략으로 시작
python scripts/start_trading.py

# 또는 다른 전략 선택
python scripts/start_trading.py --strategy ma_cross
python scripts/start_trading.py --strategy rsi
python scripts/start_trading.py --strategy advanced_scalping

# 전략 정보 확인
python scripts/start_trading.py --info
```

## 테스트

구현된 기능들을 테스트하려면:
```bash
python test_websocket_api.py
```

## 설정 예시

### WebSocket 채널 설정
```python
# config/settings.py
WEBSOCKET_CHANNELS = ["ticker"]  # 또는 ["orderbook"] 또는 ["ticker", "orderbook"]
WEBSOCKET_HEARTBEAT_TIMEOUT = 30.0
WEBSOCKET_MAX_RETRIES = -1  # 무제한 재시도
```

### Rate Limiting 커스터마이징
```python
from src.utils.rate_limiter import RateLimiter, TokenBucket

# 커스텀 제한 설정
custom_limiter = RateLimiter({
    'order': TokenBucket(5, 5),    # 초당 5개로 제한
    'market': TokenBucket(200, 200) # 초당 200개로 증가
})
```

### 전략 설정
```python
# config/strategy_config.py
SYMBOLS = ["KRW-BTC", "KRW-ETH"]  # 거래 종목

# 종목별 개별 설정
SYMBOL_SPECIFIC_CONFIG = {
    "KRW-BTC": {
        "take_profit_pct": 0.3,
        "trailing_stop_enabled": True,
        "partial_close_enabled": True,
    }
}

# 전략 매니저 사용
from src.strategy.strategy_manager import StrategyManager

strategy_manager = StrategyManager("advanced_scalping")
strategy_manager.prepare_all_strategies()
```

## Docker로 실행하기
```bash
# 환경 변수 파일 생성 및 편집
cp env.example .env  # API 키·토큰 입력

# 컨테이너 빌드 & 실행
docker compose up -d --build

# 로그 확인
docker compose logs -f
```

Docker 환경에서는 `/app/data` 디렉터리가 호스트의 `./data`에 마운트되어
데이터베이스·캔들 파일이 컨테이너 재시작 후에도 유지됩니다. 전략 변경은
`.env` 의 `STRATEGY` 변수 혹은 `docker compose run -e STRATEGY=ma_cross` 방식으로
쉽게 적용할 수 있습니다. 