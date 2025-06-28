from __future__ import annotations
import sqlite3
from pathlib import Path
from threading import Event
from queue import Queue, Empty
from datetime import datetime

from config.settings import BASE_DIR
from src.utils.logger import get_logger

logger = get_logger(__name__)

DB_PATH = Path(BASE_DIR / "data" / "autocoin.db")
DB_PATH.parent.mkdir(parents=True, exist_ok=True)


class DBWriter:
    """거래 정보를 비동기적으로 SQLite 에 기록"""

    TABLE_SCHEMA = (
        "CREATE TABLE IF NOT EXISTS trade_log ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "timestamp TEXT, "
        "side TEXT, "
        "price REAL, "
        "volume REAL)"
    )

    @staticmethod
    def _get_conn() -> sqlite3.Connection:
        conn = sqlite3.connect(DB_PATH)
        conn.execute(DBWriter.TABLE_SCHEMA)
        return conn

    @staticmethod
    def run(db_q: Queue, stop_event: Event) -> None:
        conn = DBWriter._get_conn()
        cur = conn.cursor()

        while not stop_event.is_set():
            try:
                ts, side, price, volume = db_q.get(timeout=1)
                cur.execute(
                    "INSERT INTO trade_log (timestamp, side, price, volume) VALUES (?, ?, ?, ?)",
                    (ts if ts else datetime.utcnow().isoformat(), side, price, volume),
                )
                conn.commit()
            except Empty:
                continue
            except Exception as exc:
                logger.exception("DBWriter error: %s", exc)
                conn.rollback()

        conn.close() 