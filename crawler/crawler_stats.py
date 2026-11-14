"""Snapshot of crawl totals: pages, errors, speed, status codes, domains."""

from __future__ import annotations

import time
from collections import Counter
from typing import Any
from urllib.parse import urlsplit

class CrawlerStats:
    """Read-only summary. Call summary() whenever you need numbers."""

    def __init__(self, crawler: Any, *, top_n: int = 10) -> None:
        self._crawler = crawler
        self.top_n = top_n

    def summary(self) -> dict:
        """Return a dict of crawl stats."""
        c = self._crawler
        elapsed = time.monotonic() - c._stats_start
        pages = len(c.processed_urls)
        failed = len(c.failed_urls)
        speed = pages / elapsed if elapsed > 0 else 0.0
        status_codes: Counter[int] = Counter()
        domains: Counter[str] = Counter()
        for url, page in c.processed_urls.items():
            raw = page.get("status_code")
            try:
                status_codes[int(raw)] += 1
            except (TypeError, ValueError):
                pass
            host = urlsplit(url).netloc.lower()
            if host:
                domains[host] += 1
        for row in c.error_log:
            if row.get("result") != "failure":
                continue
            status = row.get("status")
            if status is None:
                continue
            try:
                status_codes[int(status)] += 1
            except (TypeError, ValueError):
                pass
        return {
            "pages_processed": pages,
            "successful_requests": pages,
            "failed_requests": failed,
            "avg_pages_per_second": speed,
            "status_codes": dict(status_codes),
            "top_domains": domains.most_common(self.top_n),
            "elapsed_seconds": elapsed,
        }
