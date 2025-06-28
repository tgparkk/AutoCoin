from __future__ import annotations
import time
import threading
from functools import wraps
from typing import Dict, Callable, Any
from src.utils.logger import get_logger

logger = get_logger(__name__)


class TokenBucket:
    """토큰 버킷 알고리즘을 구현한 Rate Limiter"""
    
    def __init__(self, capacity: int, refill_rate: float):
        """
        Args:
            capacity: 버킷의 최대 토큰 수
            refill_rate: 초당 토큰 보충 비율
        """
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.tokens = float(capacity)
        self.last_refill = time.time()
        self.lock = threading.Lock()
    
    def consume(self, tokens: int = 1) -> bool:
        """토큰을 소비하고 성공 여부를 반환"""
        with self.lock:
            now = time.time()
            # 토큰 보충
            time_passed = now - self.last_refill
            self.tokens = min(self.capacity, self.tokens + time_passed * self.refill_rate)
            self.last_refill = now
            
            # 토큰 소비 가능한지 확인
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            return False
    
    def wait_for_token(self, tokens: int = 1, timeout: float = 30.0) -> bool:
        """토큰이 사용 가능할 때까지 대기"""
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            if self.consume(tokens):
                return True
            
            # 필요한 토큰이 사용 가능해질 때까지 대기 시간 계산
            with self.lock:
                if self.tokens < tokens:
                    wait_time = (tokens - self.tokens) / self.refill_rate
                    time.sleep(min(wait_time, 0.1))  # 최대 0.1초씩 대기
                else:
                    time.sleep(0.01)
        
        return False


class RateLimiter:
    """API 엔드포인트별 Rate Limiting 관리"""
    
    # 업비트 API 제한 (초당 요청 수)
    DEFAULT_LIMITS = {
        'default': TokenBucket(10, 10),  # 기본: 초당 10개
        'order': TokenBucket(8, 8),      # 주문: 초당 8개  
        'cancel': TokenBucket(8, 8),     # 취소: 초당 8개
        'account': TokenBucket(30, 30),  # 계좌: 초당 30개
        'market': TokenBucket(100, 100), # 시세: 초당 100개
    }
    
    def __init__(self, custom_limits: Dict[str, TokenBucket] = None):
        self.buckets = self.DEFAULT_LIMITS.copy()
        if custom_limits:
            self.buckets.update(custom_limits)
    
    def acquire(self, endpoint: str = 'default', tokens: int = 1, 
                wait: bool = True, timeout: float = 30.0) -> bool:
        """토큰 획득"""
        bucket = self.buckets.get(endpoint, self.buckets['default'])
        
        if wait:
            success = bucket.wait_for_token(tokens, timeout)
            if not success:
                logger.warning("Rate limit 타임아웃: %s", endpoint)
            return success
        else:
            return bucket.consume(tokens)


# 전역 Rate Limiter 인스턴스
_global_limiter = RateLimiter()


def rate_limit(endpoint: str = 'default', tokens: int = 1, 
               wait: bool = True, timeout: float = 30.0):
    """API 호출에 Rate Limiting을 적용하는 데코레이터
    
    Args:
        endpoint: API 엔드포인트 유형 ('order', 'cancel', 'account', 'market', 'default')
        tokens: 소비할 토큰 수
        wait: 토큰이 없을 때 대기할지 여부
        timeout: 최대 대기 시간
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            # Rate limit 체크
            if not _global_limiter.acquire(endpoint, tokens, wait, timeout):
                raise Exception(f"Rate limit exceeded for {endpoint}")
            
            # 실제 API 호출
            try:
                return func(*args, **kwargs)
            except Exception as exc:
                logger.warning("API 호출 실패: %s - %s", func.__name__, exc)
                raise
        
        return wrapper
    return decorator


def get_rate_limiter() -> RateLimiter:
    """전역 Rate Limiter 인스턴스 반환"""
    return _global_limiter


def set_rate_limiter(limiter: RateLimiter) -> None:
    """전역 Rate Limiter 설정 (테스트용)"""
    global _global_limiter
    _global_limiter = limiter 