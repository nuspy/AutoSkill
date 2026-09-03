"""Small fixed-window rate limiter for unauthenticated endpoints (/dl, /git).

Backend: in-process memory (single-process mode) or Redis INCR+EXPIRE when AUTOSKILL_EVENTS=redis, so
the limit is shared by every API worker. Keys are short strings (`dl:token:<prefix>`, `dl:ip:<ip>`).
"""

from __future__ import annotations

import time
from collections import defaultdict

from autoskill.config import get_settings
from autoskill.core.errors import AppError


class RateLimited(AppError):
    status_code = 429
    code = "rate_limited"


class MemoryRateLimiter:
    def __init__(self) -> None:
        self._windows: dict[str, tuple[int, int]] = defaultdict(lambda: (0, 0))  # key -> (window start, count)

    async def hit(self, key: str, limit: int, window_s: int = 60) -> int:
        now = int(time.time())
        start, count = self._windows[key]
        if now - start >= window_s:
            start, count = now, 0
        count += 1
        self._windows[key] = (start, count)
        if len(self._windows) > 10_000:  # keep the table bounded
            for k in [k for k, (s, _) in self._windows.items() if now - s >= window_s][:5000]:
                del self._windows[k]
        if count > limit:
            raise RateLimited(
                "rate_limited", message="too many requests, slow down", retry_after=window_s - (now - start)
            )
        return count

    def reset(self) -> None:
        self._windows.clear()


class RedisRateLimiter:
    def __init__(self, url: str) -> None:
        import redis.asyncio as redis

        self._redis = redis.from_url(url)

    async def hit(self, key: str, limit: int, window_s: int = 60) -> int:
        bucket = f"autoskill:rl:{key}:{int(time.time()) // window_s}"
        count = await self._redis.incr(bucket)
        if count == 1:
            await self._redis.expire(bucket, window_s + 1)
        if count > limit:
            raise RateLimited("rate_limited", message="too many requests, slow down", retry_after=window_s)
        return int(count)

    def reset(self) -> None:  # pragma: no cover - tests use the memory backend
        pass


_limiter: MemoryRateLimiter | RedisRateLimiter | None = None


def get_rate_limiter() -> MemoryRateLimiter | RedisRateLimiter:
    global _limiter
    if _limiter is None:
        settings = get_settings()
        _limiter = RedisRateLimiter(settings.redis_url) if settings.events == "redis" else MemoryRateLimiter()
    return _limiter


def reset_rate_limiter() -> None:
    global _limiter
    _limiter = None


async def limit(key: str, per_minute: int) -> None:
    await get_rate_limiter().hit(key, per_minute)
