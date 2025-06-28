from __future__ import annotations
import pathlib

# 프로젝트 루트 경로
BASE_DIR = pathlib.Path(__file__).resolve().parent.parent

# 로그 디렉터리 생성
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True) 