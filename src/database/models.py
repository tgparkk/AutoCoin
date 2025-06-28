from __future__ import annotations

"""SQLAlchemy ORM 모델 정의 및 세션 헬퍼.

기존 SQLite 쓰기는 유지하고, 새로운 데이터 처리 로직은 이 모델을 사용합니다.
DB_URL 은 config.db_config.DB_URL 을 참조합니다.
"""

from datetime import datetime
from typing import Generator

from sqlalchemy import Column, DateTime, Enum, Float, Integer, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from config.db_config import DB_URL

# ---------------------------------------------------------------------------
# Declarative base
# ---------------------------------------------------------------------------

class Base(DeclarativeBase):
    """공통 Declarative Base."""

    __abstract__ = True
    id: int
    created_at: datetime = Column(DateTime, default=datetime.utcnow, nullable=False)


# ---------------------------------------------------------------------------
# Model definitions
# ---------------------------------------------------------------------------

class Candle(Base):
    """OHLCV 캔들 데이터."""

    __tablename__ = "candle"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(20), index=True, nullable=False)  # ex) BTC-KRW
    interval = Column(String(10), index=True, nullable=False)  # ex) 1m, 5m, 1d
    timestamp = Column(DateTime, index=True, nullable=False)

    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    volume = Column(Float, nullable=False)


class Trade(Base):
    """실시간 체결 로그."""

    __tablename__ = "trade"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)
    symbol = Column(String(20), nullable=False)
    side = Column(Enum("BUY", "SELL", name="trade_side"), nullable=False)
    price = Column(Float, nullable=False)
    qty = Column(Float, nullable=False)  # executed quantity
    fee = Column(Float, default=0.0, nullable=False)


# ---------------------------------------------------------------------------
# Engine & Session
# ---------------------------------------------------------------------------

_engine = create_engine(DB_URL, echo=False, future=True)
_SessionFactory = sessionmaker(bind=_engine, autoflush=False, autocommit=False, future=True)


def init_db() -> None:
    """테이블 생성 (존재하면 무시)."""

    Base.metadata.create_all(_engine)


def get_session() -> Generator[Session, None, None]:
    """의존성 주입 형태로 사용할 세션 제너레이터 (FastAPI 스타일)."""

    session: Session = _SessionFactory()
    try:
        yield session
    finally:
        session.close()


# 편의상 직접 import 가능한 객체 노출
SessionLocal = _SessionFactory 