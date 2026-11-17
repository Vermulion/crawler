from __future__ import annotations

import asyncio
from typing import Optional, Protocol

class Frontier(Protocol):
    async def add(self, url: str, *, depth: int = 0) -> bool:
        """True if url is new and was queued."""
        ...

    async def get(self) -> Optional[tuple[str, int]]:
        """Next (url, depth), or None if idle."""
        ...

class InMemoryFrontier:
    """Share this object between two crawlers in one process (tests / demo)."""

    def __init__(self, *, max_pages: int = 100, max_depth: Optional[int] = None) -> None:
        self.max_pages = max_pages
        self.max_depth = max_depth
        self._pending: asyncio.Queue[tuple[str, int]] = asyncio.Queue()
        self._seen: set[str] = set()
        self._lock = asyncio.Lock()

    async def add(self, url: str, *, depth: int = 0) -> bool:
        if self.max_depth is not None and depth > self.max_depth:
            return False
        async with self._lock:
            if url in self._seen:
                return False
            if len(self._seen) >= self.max_pages:
                return False
            self._seen.add(url)
        await self._pending.put((url, depth))
        return True

    async def get(self) -> Optional[tuple[str, int]]:
        try:
            return self._pending.get_nowait()
        except asyncio.QueueEmpty:
            return None