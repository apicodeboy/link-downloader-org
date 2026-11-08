"""Fixed-window rate limiting, backed by Redis with an in-memory fallback."""
from __future__ import annotations

import logging
import threading
import time

log = logging.getLogger(__name__)


class RateLimiter:
    def __init__(self, redis_client=None, prefix: str = "vd:rl"):
        self.redis = redis_client
        self.prefix = prefix
        self._mem: dict[str, tuple[int, float]] = {}
        self._lock = threading.Lock()

    def hit(self, bucket: str, key: str, limit: int, window: int = 60) -> tuple[bool, int]:
        """Record a hit. Returns (allowed, seconds_until_reset)."""
        if limit <= 0:
            return True, 0
        now = time.time()
        window_start = int(now // window) * window
        reset = int(window_start + window - now) + 1
        full_key = f"{self.prefix}:{bucket}:{key}:{window_start}"
        if self.redis is not None:
            try:
                pipe = self.redis.pipeline()
                pipe.incr(full_key)
                pipe.expire(full_key, window + 5)
                count = pipe.execute()[0]
                return count <= limit, reset
            except Exception as exc:  # Redis down: fall back rather than fail open silently
                log.warning("rate limiter falling back to memory: %s", exc)
        with self._lock:
            if len(self._mem) > 10000:
                self._mem = {k: v for k, v in self._mem.items() if v[1] > now}
            count, expires = self._mem.get(full_key, (0, window_start + window))
            count += 1
            self._mem[full_key] = (count, expires)
        return count <= limit, reset
