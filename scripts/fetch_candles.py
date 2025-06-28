#!/usr/bin/env python
"""캔들·틱 데이터 수집 스크립트

Usage examples
--------------
python scripts/fetch_candles.py BTC-KRW 1m 2023-08-01 2023-08-02 --csv --db
python scripts/fetch_candles.py BTC-KRW ETH-KRW 5m 2023-01-01 2023-01-31 --csv

• Upbit REST API 를 호출하여 200개씩 페이징 다운로드합니다.
• --csv 플래그: data/csv/ 디렉터리에 CSV 저장
• --db  플래그: SQLAlchemy Candle 테이블에 bulk insert

참고: Upbit 분당 요청 제한 10이므로 호출 간 0.12초 sleep 을 넣었습니다.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List

import requests
from tqdm import tqdm

from config.settings import BASE_DIR
from src.database.models import Candle, SessionLocal, init_db

CSV_DIR = BASE_DIR / "data" / "csv"
CSV_DIR.mkdir(parents=True, exist_ok=True)

# ----------------------------------------------------------------------------
# Upbit endpoint helpers
# ----------------------------------------------------------------------------

MINUTE_MAP = {
    "1m": 1,
    "3m": 3,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
}

DAY_MAP = {"1d": "days"}

BASE_URL = "https://api.upbit.com/v1/candles"
HEADERS = {"Accept": "application/json"}


# ----------------------------------------------------------------------------
# Utility functions
# ----------------------------------------------------------------------------

def parse_iso(dt_str: str) -> datetime:
    """YYYY-MM-DD 또는 YYYY-MM-DDTHH:MM:SS 형태를 datetime 으로."""

    try:
        return datetime.fromisoformat(dt_str).replace(tzinfo=timezone.utc)
    except ValueError as exc:  # pragma: no cover – CLI 유효성 검사용
        print(f"Invalid date format: {dt_str}", file=sys.stderr)
        raise SystemExit(1) from exc


def build_url(interval: str) -> str:
    """Upbit 캔들 엔드포인트 URL 구성."""

    if interval in MINUTE_MAP:
        unit = MINUTE_MAP[interval]
        return f"{BASE_URL}/minutes/{unit}"
    if interval in DAY_MAP:
        unit = DAY_MAP[interval]
        return f"{BASE_URL}/{unit}"
    raise ValueError(f"Unsupported interval: {interval}")


def fetch_batch(symbol: str, interval: str, to: datetime) -> List[dict]:
    """Upbit API 한 번 호출(최대 200개) 결과 반환 (신규→과거 순)."""

    url = build_url(interval)
    params = {
        "market": symbol,
        "to": to.strftime("%Y-%m-%dT%H:%M:%S"),
        "count": 200,
    }
    resp = requests.get(url, params=params, headers=HEADERS, timeout=10)
    resp.raise_for_status()
    return resp.json()


def transform_record(rec: dict, symbol: str, interval: str) -> dict:
    """Upbit JSON → DB 매핑."""

    return {
        "symbol": symbol,
        "interval": interval,
        "timestamp": datetime.fromisoformat(rec["candle_date_time_utc"].replace("Z", "+00:00")),
        "open": rec["opening_price"],
        "high": rec["high_price"],
        "low": rec["low_price"],
        "close": rec["trade_price"],
        "volume": rec["candle_acc_trade_volume"],
    }


# ----------------------------------------------------------------------------
# Main download routine
# ----------------------------------------------------------------------------

def collect_candles(symbol: str, interval: str, start: datetime, end: datetime) -> List[dict]:
    data: List[dict] = []
    current_to = end
    pbar = tqdm(desc=f"{symbol} {interval}", unit="batch")

    while True:
        batch = fetch_batch(symbol, interval, current_to)
        if not batch:
            break

        # Upbit 는 최신→과거 순 반환, 역순 정렬
        for rec in reversed(batch):
            ts = datetime.fromisoformat(rec["candle_date_time_utc"].replace("Z", "+00:00"))
            if ts < start:
                return data
            data.append(transform_record(rec, symbol, interval))

        # 다음 루프: 가장 오래된 시각으로 갱신 (이미 포함됐으므로 1초 빼기)
        oldest_ts = datetime.fromisoformat(batch[-1]["candle_date_time_utc"].replace("Z", "+00:00"))
        current_to = oldest_ts
        time.sleep(0.12)  # rate-limit safety
        pbar.update(1)

    return data


# ----------------------------------------------------------------------------
# Database insertion
# ----------------------------------------------------------------------------

def save_to_db(records: List[dict]) -> None:
    if not records:
        return
    init_db()
    with SessionLocal.begin() as session:
        session.bulk_insert_mappings(Candle, records)


# ----------------------------------------------------------------------------
# CSV export
# ----------------------------------------------------------------------------

def save_to_csv(symbol: str, interval: str, records: List[dict]) -> Path | None:
    if not records:
        return None
    filename = f"{symbol.replace('-', '')}_{interval}_{records[0]['timestamp'].date()}_{records[-1]['timestamp'].date()}.csv"
    path = CSV_DIR / filename
    fieldnames = list(records[0].keys())
    with path.open("w", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)
    return path


# ----------------------------------------------------------------------------
# CLI entry
# ----------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Upbit 캔들 데이터 수집")
    parser.add_argument("symbols", nargs="+", help="예: BTC-KRW ETH-KRW")
    parser.add_argument("interval", help="1m, 3m, 5m, 15m, 1h, 1d 중 하나")
    parser.add_argument("start_date", help="시작일자 ISO (YYYY-MM-DD[THH:MM:SS])")
    parser.add_argument("end_date", help="종료일자 ISO (YYYY-MM-DD[THH:MM:SS])")
    parser.add_argument("--csv", action="store_true", help="CSV 저장 활성화")
    parser.add_argument("--db", action="store_true", help="DB 저장 활성화")

    args = parser.parse_args()

    start = parse_iso(args.start_date)
    end = parse_iso(args.end_date)

    if start >= end:
        print("[ERROR] start_date must be earlier than end_date", file=sys.stderr)
        sys.exit(1)

    for symbol in args.symbols:
        records = collect_candles(symbol, args.interval, start, end)
        print(f"{symbol}: fetched {len(records)} rows")
        if args.csv:
            path = save_to_csv(symbol, args.interval, records)
            print(f"CSV saved → {path}")
        if args.db:
            save_to_db(records)
            print("DB insert completed")


if __name__ == "__main__":
    main() 