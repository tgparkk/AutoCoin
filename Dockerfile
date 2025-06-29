FROM python:3.11-slim

# 환경 변수 설정 – 캐시 파일 생성 방지 및 로그 버퍼링 비활성화
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# 작업 디렉터리
WORKDIR /app

# Python 버전 확인 및 시스템 의존성 설치
RUN python --version && \
    apt-get update && \
    apt-get install -y --no-install-recommends build-essential && \
    rm -rf /var/lib/apt/lists/*

# 파이썬 의존성 복사 및 설치
COPY requirements.txt ./
RUN pip install --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt && \
    python -c "import sys; print(f'Python: {sys.version}'); import telegram; print(f'python-telegram-bot: {telegram.__version__}'); import aiolimiter; print('aiolimiter: OK')"

# 프로젝트 소스 복사
COPY . .

# 기본 전략 환경 변수 (docker run -e STRATEGY=ma_cross 로 덮어쓰기 가능)
ENV STRATEGY=scalping

# 컨테이너 시작 명령
CMD ["sh", "-c", "python main.py --strategy ${STRATEGY:-scalping}"] 