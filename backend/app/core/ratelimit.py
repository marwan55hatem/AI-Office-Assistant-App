"""A small sliding-window rate limiter for the login and join endpoints.

It keeps its counters in memory, which is enough for one server process. When the
backend runs as several instances, replace it with a shared store (e.g. Redis)
behind the same ``hit`` method.
"""
import threading
import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self, window_seconds: float = 60.0):
        self.window = window_seconds
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int) -> bool:
        """Record one attempt for ``key``; return False when the limit is exceeded."""
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > self.window:
                hits.popleft()
            if len(hits) >= limit:
                return False
            hits.append(now)
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


login_limiter = RateLimiter()
