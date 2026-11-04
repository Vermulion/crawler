from __future__ import annotations

import asyncio
import time
import random
from typing import Optional


class RateLimiter:
    """Wait so requests do not exceed requests_per_second."""
    def __init__(
        self,
        requests_per_second: float = 1.0,
        per_domain: bool = True,
        min_delay: float = 0.0,
        jitter: float = 0.0,
    ) -> None:
        if requests_per_second <= 0:
            raise ValueError("requests_per_second must be > 0")
        if min_delay < 0 or jitter < 0:
            raise ValueError("min_delay and jitter must be >= 0")
            
        self.min_delay = min_delay
        self.jitter = jitter
        self.requests_per_second = requests_per_second
        self.per_domain = per_domain
        self._interval = 1.0 / requests_per_second
        self._last: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._meta_lock = asyncio.Lock()

    async def _lock_for(self, key: str) -> asyncio.Lock:
        async with self._meta_lock:
            if key not in self._locks:
                self._locks[key] = asyncio.Lock()
        return self._locks[key]


    def _key(self, domain: Optional[str]) -> str:
        if not self.per_domain:
            return "_global"
        return (domain or "").strip().lower() or "_global"

    async def acquire(self, domain: str = None, *, min_interval: float = 0.0) -> None:
        """Block until this domain (or the global clock) may send a request."""
        key = self._key(domain)
        lock = await self._lock_for(key)
        async with lock:
            now = time.monotonic()
            last = self._last.get(key, 0.0)
            gap = max(self._interval, min_interval, self.min_delay)
            wait = gap - (now - last)
            if wait < 0:
                wait = 0.0
            if self.jitter > 0:
                wait += random.uniform(0, self.jitter)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last[key] = time.monotonic()
