from __future__ import annotations

"""Database configuration.

이 모듈은 데이터베이스 파일 경로와 SQLAlchemy 연결 URL을 정의합니다.
SQLite → PostgreSQL 등으로 전환 시 DB_URL 값만 변경하면 됩니다.
"""

import pathlib
from config.settings import BASE_DIR

# data 디렉터리 보장
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

# SQLite 파일 경로
DB_PATH: pathlib.Path = DATA_DIR / "autocoin.db"

# SQLAlchemy 연결 URL
DB_URL: str = f"sqlite:///{DB_PATH}" 