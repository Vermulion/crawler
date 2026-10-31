from __future__ import annotations

import heapq
from nt import error
from typing import Iterable, Optional


class CrawlerQueue:
    """Hold URLs waiting to be crawled and remember URLs already seen."""

    def __init__(
        self,
        start_urls: Optional[Iterable[str]] = None,
        *,
        max_pages: Optional[int] = None,
    ) -> None:
        if max_pages is not None and max_pages < 1:
            raise ValueError("max_pages must be >= 1")

        self.max_pages = max_pages
        self._pending: list[tuple[int, int, str]] = []
        self._seen: set[str] = set()
        self._in_progress: set[str] = set()
        self._processed: set[str] = set()
        self._failed: dict[str, str] = {}
        self._seq = 0

        if start_urls is not None:
            for url in start_urls:
                self.add_url(url)
    
    def add_url(self, url: str, priority: int = 0) -> None:
        """Queue a URL if it is new and the page limit is not reached.

        Larger ``priority`` is fetched first. Same priority keeps insertion order.
        """
        if url in self._seen:
            return
        if self.max_pages is not None and len(self._seen) >= self.max_pages:
            return
        
        self._seen.add(url)
        # heapq is a min-heap: store -priority so bigger numbers come out first.
        heapq.heappush(self._pending, (-priority, self.seq, url))
        self.seq += 1

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
    
