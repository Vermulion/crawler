from __future__ import annotations

import heapq
from typing import Iterable, Optional
from crawler.url_filter import URLFilter


class CrawlerQueue:
    """Hold URLs waiting to be crawled and remember URLs already seen."""

    def __init__(
        self,
        start_urls: Optional[Iterable[str]] = None,
        *,
        max_pages: Optional[int] = None,
        max_depth: Optional[int] = None,
        url_filter: Optional[URLFilter] = None,

    ) -> None:
        if max_pages is not None and max_pages < 1:
            raise ValueError("max_pages must be >= 1")
        if max_depth is not None and max_depth < 0:
            raise ValueError("max_depth must be >= 0")

        self.max_pages = max_pages
        self.max_depth = max_depth
        self._pending: list[tuple[int, int, str]] = []
        self._seen: set[str] = set()
        self._in_progress: set[str] = set()
        self._processed: set[str] = set()
        self._failed: dict[str, str] = {}
        self._seq = 0
        self._depths: dict[str, int] = {}
        self.url_filter = url_filter

        if start_urls is not None:
            for url in start_urls:
                self.add_url(url)
    
    def add_url(self, url: str, priority: int = 0, depth: int = 0) -> None:

        if self.url_filter is not None and not self.url_filter.allow(url):
            return
        if url in self._seen:
            return
        if self.max_depth is not None and depth > self.max_depth:
            return
        if self.max_pages is not None and len(self._seen) >= self.max_pages:
            return

        self._seen.add(url)
        self._depths[url] = depth
        heapq.heappush(self._pending, (-priority, self._seq, url))
        self._seq += 1

    async def get_next(self) -> str | None:
        """Take the highest-priority pending URL, or None if the queue is empty."""
        if not self._pending:
            return None
        _priority, _ser, url = heapq.heappop(self._pending)
        self._in_progress.add(url)
        return url

    def mark_processed(self, url: str) -> None:
        """Record a successful crawl."""
        self._in_progress.discard(url)
        self._processed.add(url)

    def mark_failed(self, url: str, error: str) -> None:
        """Record a failed crawl and keep the error text."""
        self._in_progress.discard(url)
        self._failed[url] = error

    def get_stats(self) -> dict:
        """Return counts for the current queue state."""
        return {
        "pending": len(self._pending),
        "in_progress": len(self._in_progress),
        "processed": len(self._processed),
        "failed": len(self._failed),
        "seen": len(self._seen),
        }
    
