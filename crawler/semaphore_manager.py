from __future__ import annotations

import asyncio
from collections import defaultdict
from urllib.parse import urlparse


class SemaphoreManager:
    """Limit global and per-domain in-flight requests."""

    def __init__(self, max_global: int = 10, max_per_domain: int = 2) -> None:
        if max_global < 1:
            raise ValueError("max_global must be >= 1")
        if max_per_domain < 1:
            raise ValueError("max_per_domain must be >= 1")

        self.max_global = max_global
        self.max_per_domain = max_per_domain
        self._global = asyncio.Semaphore(max_global)
        self._per_domain: dict[str, asyncio.Semaphore] = {}
        self._lock = asyncio.Lock()
        self._active_global = 0
        self._active_per_domain: dict[str, int] = defaultdict(int)
        self._active_urls: set[str] = set()

    @staticmethod
    def _host(url: str) -> str:
        host = urlparse(url).netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        return host or url

    async def _domain_semaphore(self, host: str) -> asyncio.Semaphore:
        async with self._lock:
            if host not in self._per_domain:
                self._per_domain[host] = asyncio.Semaphore(self.max_per_domain)
            return self._per_domain[host]

    async def acquire(self, url: str) -> None:
        """Wait until a global slot and a domain slot are free."""
        host = self._host(url)
        await self._global.acquire()
        try:
            domain_sem = await self._domain_semaphore(host)
            await domain_sem.acquire()
        except BaseException:
            self._global.release()
            raise
        self._active_global += 1
        self._active_per_domain[host] += 1
        self._active_urls.add(url)

    def release(self, url: str) -> None:
        """Free both slots after a successful acquire."""
        host = self._host(url)
        if url in self._active_urls:
            self._active_urls.discard(url)
            self._active_global = max(0, self._active_global - 1)
            self._active_per_domain[host] = max(
                0, self._active_per_domain[host] - 1
            )
        domain_sem = self._per_domain.get(host)
        if domain_sem is not None:
            domain_sem.release()
        self._global.release()

    def limit(self, url: str) -> "_Slot":
        """Use as: async with manager.limit(url): ..."""
        return _Slot(self, url)

    def get_stats(self) -> dict:
        """How many requests are in flight right now."""
        return {
            "active": self._active_global,
            "active_urls": sorted(self._active_urls),
            "active_per_domain": dict(self._active_per_domain),
            "max_global": self.max_global,
            "max_per_domain": self.max_per_domain,
        }


class _Slot:
    """Helper so 'async with manager.limit(url)' acquires and releases."""

    def __init__(self, manager: SemaphoreManager, url: str) -> None:
        self._manager = manager
        self._url = url

    async def __aenter__(self) -> SemaphoreManager:
        await self._manager.acquire(self._url)
        return self._manager

    async def __aexit__(self, exc_type, exc, tb) -> None:
        self._manager.release(self._url)