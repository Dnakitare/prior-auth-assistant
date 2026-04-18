"""Brute-force lockout for auth endpoints.

Counts failed attempts per key (typically client IP) in a sliding window.
Backed by Redis when available, in-memory otherwise. Returns (locked, retry_after).

This intentionally uses its own backend rather than the request-rate limiter
so auth lockouts don't compete with legitimate traffic budgets.
"""

from __future__ import annotations

import time
from collections import defaultdict

from src.core.config import settings


class _InMemoryLockoutBackend:
    def __init__(self) -> None:
        # key -> list[timestamp of failure]
        self._failures: dict[str, list[float]] = defaultdict(list)

    async def record_failure(self, key: str, window: int) -> int:
        now = time.time()
        cutoff = now - window
        bucket = [t for t in self._failures[key] if t > cutoff]
        bucket.append(now)
        self._failures[key] = bucket
        return len(bucket)

    async def clear(self, key: str) -> None:
        self._failures.pop(key, None)

    async def failures(self, key: str, window: int) -> int:
        now = time.time()
        cutoff = now - window
        bucket = [t for t in self._failures[key] if t > cutoff]
        self._failures[key] = bucket
        return len(bucket)


class _RedisLockoutBackend:
    def __init__(self, client) -> None:
        self._client = client

    def _k(self, key: str) -> str:
        return f"lockout:{key}"

    async def record_failure(self, key: str, window: int) -> int:
        pipe = self._client.pipeline()
        pipe.incr(self._k(key), 1)
        pipe.expire(self._k(key), window)
        count, _ = await pipe.execute()
        return int(count)

    async def clear(self, key: str) -> None:
        await self._client.delete(self._k(key))

    async def failures(self, key: str, window: int) -> int:
        val = await self._client.get(self._k(key))
        return int(val) if val is not None else 0


class LoginLockout:
    """Fixed-window failure counter with configurable threshold.

    After `max_failures` within `window_seconds`, the key is considered
    locked out; subsequent checks return True until the window rolls.
    """

    def __init__(
        self,
        max_failures: int = 5,
        window_seconds: int = 900,  # 15 minutes
    ) -> None:
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self._backend: _InMemoryLockoutBackend | _RedisLockoutBackend | None = None

    def attach_redis(self, client) -> None:
        self._backend = _RedisLockoutBackend(client)

    def _ensure_backend(self) -> _InMemoryLockoutBackend | _RedisLockoutBackend:
        if self._backend is None:
            self._backend = _InMemoryLockoutBackend()
        return self._backend

    async def is_locked(self, key: str) -> tuple[bool, int]:
        """Return (locked, retry_after_seconds)."""
        backend = self._ensure_backend()
        count = await backend.failures(key, self.window_seconds)
        if count >= self.max_failures:
            return True, self.window_seconds
        return False, 0

    async def record_failure(self, key: str) -> int:
        return await self._ensure_backend().record_failure(key, self.window_seconds)

    async def reset(self, key: str) -> None:
        await self._ensure_backend().clear(key)


# Module-level instance — configured in main.py lifespan.
login_lockout = LoginLockout()
