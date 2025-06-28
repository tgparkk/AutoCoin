from __future__ import annotations
import os
import configparser
from pathlib import Path

# --------------------------------------------------
#   INI 파일 로딩
# --------------------------------------------------
CONFIG_PATH = Path(__file__).resolve().parent / "config.ini"
parser = configparser.ConfigParser()
if CONFIG_PATH.exists():
    parser.read(CONFIG_PATH, encoding="utf-8")
else:
    parser = None

# Upbit
UPBIT_ACCESS_KEY: str | None = (
    parser.get("upbit", "access_key") if parser and parser.has_option("upbit", "access_key") else os.getenv("UPBIT_ACCESS_KEY")
)
UPBIT_SECRET_KEY: str | None = (
    parser.get("upbit", "secret_key") if parser and parser.has_option("upbit", "secret_key") else os.getenv("UPBIT_SECRET_KEY")
)

# Telegram
TELEGRAM_TOKEN: str | None = (
    parser.get("telegram", "token") if parser and parser.has_option("telegram", "token") else os.getenv("TELEGRAM_TOKEN")
)
TELEGRAM_CHAT_ID: int | None = None
if parser and parser.has_option("telegram", "chat_id"):
    TELEGRAM_CHAT_ID = parser.getint("telegram", "chat_id")
elif os.getenv("TELEGRAM_CHAT_ID"):
    TELEGRAM_CHAT_ID = int(os.getenv("TELEGRAM_CHAT_ID")) 