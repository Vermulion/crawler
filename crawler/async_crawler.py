"""Base async HTTP crawler with concurrency control."""

from __future__ import annotations

import sys
import time
import asyncio
from typing import Optional

import aiohttp

from crawler.crawler_queue import CrawlerQueue
from crawler.html_parser import HTMLParser
from crawler.semaphore_manager import SemaphoreManager
from crawler.url_filter import URLFilter


class AsyncCrawler:
    """Fetch one or many URLs concurrently using a shared aiohttp session.

    Concurrency is limited by an asyncio.Semaphore so at most
    ``max_concurrent`` requests run at the same time.
    """
    def _print_progress(self, queue: CrawlerQueue, *, start: float) -> None:
        stats = queue.get_stats()
        processed = stats["processed"]
        pending = stats["pending"]
        errors = stats["failed"]
        elapsed = time.monotonic() - start
        speed = processed / elapsed if elapsed > 0 else 0.0
        line = (
            f"processed={processed}  queue={pending}  "
            f"errors={errors}  speed={speed:.2f} pages/s"
        )
        print(f"\r{line:<80}", end="", file=sys.stderr, flush=True)

    def __init__(
        self,
        max_concurrent: int = 10,
        max_per_domain: int = 2,
        *,
        same_domain_only: bool = True,
        include_patterns: Optional[list[str]] = None,
        exclude_patterns: Optional[list[str]] = None,
    )  -> None:
        if max_concurrent < 1:
            raise ValueError("max_concurrent must be >= 1")

        self.max_concurrent = max_concurrent
        self.max_per_domain = max_per_domain
        self.limiter = SemaphoreManager(
            max_global=max_concurrent,
            max_per_domain=max_per_domain,
        )   
        self.parser = HTMLParser()
        self.visited_urls: set[str] = set()
        self.failed_urls: dict[str, str] = {}
        self.processed_urls: dict[str, dict] = {}
        self._session: Optional[aiohttp.ClientSession] = None
        self.same_domain_only = same_domain_only
        self.include_patterns = list(include_patterns or [])
        self.exclude_patterns = list(exclude_patterns or [])
        
    async def fetch_and_parse(self, url: str) -> dict:
        html = await self.fetch_url(url)
        return await self.parser.parse_html(html, url)
    
    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def fetch_url(self, url: str) -> str:
        """Load a single page and return its response body as text."""
        session = await self._get_session()
        async with self.limiter.limit(url):
            async with session.get(url) as response:
                response.raise_for_status()
                return await response.text()

    async def fetch_urls(self, urls: list[str]) -> dict[str, str]:
        """Load many URLs in parallel. Returns {url: body} for successful fetches.

        Failed URLs are omitted from the result. Each request still respects
        the ``max_concurrent`` limit.
        """
        if not urls:
            return {}

        async def _safe_fetch(url: str) -> tuple[str, Optional[str]]:
            try:
                body = await self.fetch_url(url)
                return url, body
            except Exception:
                return url, None

        results = await asyncio.gather(*(_safe_fetch(url) for url in urls))
        return {url: body for url, body in results if body is not None}

    async def crawl(
        self,
        start_urls: list[str],
        max_pages: int = 100,
        *,
        max_depth: Optional[int] = None,
    ) -> dict[str, dict]:
        """Follow links from start_urls. Fill visited / processed / failed state."""

        if max_pages < 1:
            raise ValueError("max_pages must be >= 1")
        
        self.visited_urls.clear()
        self.failed_urls.clear()
        self.processed_urls.clear()

        url_filter = URLFilter(
            same_domain_only=self.same_domain_only,
            allowed_hosts=start_urls,
            include_patterns=self.include_patterns,
            exclude_patterns=self.exclude_patterns,
        )
        queue = CrawlerQueue(
            start_urls,
            max_pages=max_pages,
            max_depth=max_depth,
            url_filter=url_filter,
        )
        start = time.monotonic()
        self._print_progress(queue, start=start)

        async def worker() -> None:
            while True:
                url = await queue.get_next()
                if url is None:
                    # Queue empty. If nobody is fetching, we are done.
                    # If others are still fetching, they may add new links.
                    if not queue._in_progress:
                        return
                    await asyncio.sleep(0)
                    continue

                self.visited_urls.add(url)
                depth = queue._depths.get(url, 0)
                try:
                    page = await self.fetch_and_parse(url)
                    queue.mark_processed(url)
                    self.processed_urls[url] = page
                    for link in page.get("links") or []:
                        queue.add_url(link, depth=depth + 1)
                except Exception as exc:
                    queue.mark_failed(url, f"{type(exc).__name__}: {exc}")
                    self.failed_urls[url] = f"{type(exc).__name__}: {exc}"
                self._print_progress(queue, start=start)

        workers = max(1, min(self.max_concurrent, max_pages))
        await asyncio.gather(*(worker() for _ in range(workers)))
        self._print_progress(queue, start=start)
        print(file=sys.stderr)

        return self.processed_urls

    async def close(self) -> None:
        """Close the underlying HTTP session."""
        if self._session is not None and not self._session.closed:
            await self._session.close()
            self._session = None

    async def __aenter__(self) -> "AsyncCrawler":
        await self._get_session()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()
