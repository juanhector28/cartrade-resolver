"""In-memory rate limiter, sliding window per IP.

For production scale move this to Redis. Sufficient for ~thousands of requests/day.
"""
from __future__ import annotations
import time
import os
from collections import defaultdict, deque
from threading import Lock

WINDOW_SECONDS = int(os.environ.get("RATE_WINDOW_SECONDS", "3600"))  # 1 hour
MAX_REQUESTS = int(os.environ.get("RATE_MAX_REQUESTS", "30"))

_buckets: dict[str, deque] = defaultdict(deque)
_lock = Lock()


def check(ip: str) -> tuple[bool, int]:
    """Return (allowed, remaining). If not allowed, remaining=0."""
    now = time.time()
    with _lock:
        bucket = _buckets[ip]
        # purge old entries
        cutoff = now - WINDOW_SECONDS
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= MAX_REQUESTS:
            return False, 0
        bucket.append(now)
        return True, MAX_REQUESTS - len(bucket)
