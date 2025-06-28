#!/usr/bin/env python3
"""
AutoCoin 자동매매 봇 시작 스크립트

사용법:
    python scripts/start_trading.py                    # 기본 스캘핑 전략
    python scripts/start_trading.py --strategy ma_cross # MA Cross 전략
    python scripts/start_trading.py --strategy rsi      # RSI 전략
    python scripts/start_trading.py --strategy advanced_scalping # 고급 스캘핑
"""

from __future__ import annotations
import argparse
import sys
import os

# 프로젝트 루트를 Python 경로에 추가
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from main import main


def show_strategy_info():
    """사용 가능한 전략 정보 출력"""
    strategies = {
        "scalping": "기본 스캘핑 전략 - 가격 반전 기반",
        "ma_cross": "이동평균 교차 전략 - 골든/데스 크로스",
        "rsi": "RSI 전략 - 과매수/과매도 기반",
        "advanced_scalping": "고급 스캘핑 - 트레일링 스탑 + 부분 청산"
    }
    
    print("=" * 50)
    print("AutoCoin 사용 가능한 전략:")
    print("=" * 50)
    for name, desc in strategies.items():
        print(f"  {name:20} : {desc}")
    print("=" * 50)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="AutoCoin 자동매매 봇",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    
    parser.add_argument(
        "--strategy", 
        default="scalping",
        choices=["scalping", "ma_cross", "rsi", "advanced_scalping"],
        help="사용할 전략 선택 (기본값: scalping)"
    )
    
    parser.add_argument(
        "--info",
        action="store_true",
        help="사용 가능한 전략 정보 출력"
    )
    
    parser.add_argument(
        "--no-telegram",
        action="store_true",
        help="텔레그램 연결 없이 실행"
    )
    
    args = parser.parse_args()
    
    if args.info:
        show_strategy_info()
        sys.exit(0)
    
    print(f"AutoCoin 시작 - 전략: {args.strategy} (Telegram={'ON' if not args.no_telegram else 'OFF'})")
    main(args.strategy, use_telegram=not args.no_telegram) 