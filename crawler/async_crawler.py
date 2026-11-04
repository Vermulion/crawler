"""Base async HTTP crawler with concurrency control."""

from __future__ import annotations

import asyncio
import logging
import sys
import time
import random
from typing import Optional

import aiohttp

from crawler.crawler_queue import CrawlerQueue
from crawler.html_parser import HTMLParser
from crawler.semaphore_manager import SemaphoreManager
from crawler.url_filter import URLFilter
from crawler.rate_limiter import RateLimiter
from crawler.robots_parser import RobotsDenied, RobotsParser

logger = logging.getLogger(__name__)

# Default pool size matches aiohttp's TCPConnector.limit.
_DEFAULT_POOL_LIMIT = 100


class AsyncCrawler:
    """Fetch one or many URLs concurrently using a shared aiohttp session.

    Concurrency is limited by SemaphoreManager (global + per-domain).
    The shared ClientSession uses connect/read/total timeouts and a TCP pool.
    """

    def __init__(
        self,
        max_concurrent: int = 10,
        max_per_domain: int = 2,
        *,
        connect_timeout: float = 10.0,
        read_timeout: float = 30.0,
        total_timeout: float = 60.0,
        pool_limit: int = _DEFAULT_POOL_LIMIT,
        pool_limit_per_host: Optional[int] = None,
        same_domain_only: bool = True,
        include_patterns: Optional[list[str]] = None,
        exclude_patterns: Optional[list[str]] = None,
        requests_per_second: float = 1.0,
        rate_limit_per_domain: bool = True,
        min_delay: float = 0.0,
        jitter: float = 0.0,
        max_retries: int = 0,
        backoff_factor: float = 0.5,
        backoff_max: float = 30.0,
        user_agent: str = "AsyncCrawler",
        user_agents: Optional[list[str]] = None,
    ) -> None:
        if max_concurrent < 1:
            raise ValueError("max_concurrent must be >= 1")
        if connect_timeout <= 0 or read_timeout <= 0 or total_timeout <= 0:
            raise ValueError("timeouts must be > 0")
        if pool_limit < 1:
            raise ValueError("pool_limit must be >= 1")

        self.max_concurrent = max_concurrent
        self.max_per_domain = max_per_domain
        self.connect_timeout = connect_timeout
        self.read_timeout = read_timeout
        self.total_timeout = total_timeout
        self.pool_limit = pool_limit
        self.pool_limit_per_host = (
            pool_limit_per_host if pool_limit_per_host is not None else max_concurrent
        )
        self.limiter = SemaphoreManager(
            max_global=max_concurrent,
            max_per_domain=max_per_domain,
        )
        self.requests_per_second = requests_per_second
        self.rate_limit_per_domain = rate_limit_per_domain
        self.rate_limiter = RateLimiter(
            requests_per_second=requests_per_second,
            per_domain=rate_limit_per_domain,
            min_delay=min_delay,
            jitter=jitter,
        )
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        if user_agents:
            names = [name.strip() for name in user_agents if name and name.strip()]
        else:
            names = [user_agent.strip()] if user_agent.strip() else []
        if not names:
            raise ValueError("user_agent must not be empty")
        self.user_agents = names
        self.user_agent = names[0]
        self._agent_index = 0
        self._agent_lock = asyncio.Lock()
        self.jitter = jitter
        self.robots = RobotsParser()
        self.blocked_urls: set[str] = set()
        self._request_times: list[float] = []
        self._requests_done = 0
        self._stats_start = time.monotonic()
        self._robots_lock = asyncio.Lock()
        self.parser = HTMLParser()
        self.visited_urls: set[str] = set()
        self.failed_urls: dict[str, str] = {}
        self.processed_urls: dict[str, dict] = {}
        self._session: Optional[aiohttp.ClientSession] = None
        self.same_domain_only = same_domain_only
        self.include_patterns = list(include_patterns or [])
        self.exclude_patterns = list(exclude_patterns or [])

    def _print_progress(self, queue: CrawlerQueue, *, start: float) -> None:
        stats = queue.get_stats()
        processed = stats["processed"]
        pending = stats["pending"]
        errors = stats["failed"]
        elapsed = time.monotonic() - start
        speed = processed / elapsed if elapsed > 0 else 0.0
        extra = self.get_speed_stats()
        line = (
            f"processed={processed}  queue={pending}  "
            f"errors={errors}  speed={speed:.2f} pages/s  "
            f"req/s={extra['requests_per_second']:.2f}  "
            f"avg_delay={extra['avg_delay']:.2f}s  "
            f"robots_blocked={extra['blocked']}"
        )
        print(f"\r{line:<80}", end="", file=sys.stderr, flush=True)

    def get_speed_stats(self) -> dict:
        elapsed = time.monotonic() - self._stats_start
        speed = self._requests_done / elapsed if elapsed > 0 else 0.0
        times = self._request_times
        if len(times) >= 2:
            gaps = [times[i] - times[i - 1] for i in range(1, len(times))]
            avg_delay = sum(gaps) / len(gaps)
        else:
            avg_delay = 0.0
        return {
            "requests_per_second": speed,
            "avg_delay": avg_delay,
            "blocked": len(self.blocked_urls),
            "requests": self._requests_done,
        }

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(
                total=self.total_timeout,
                connect=self.connect_timeout,
                sock_read=self.read_timeout,
            )
            connector = aiohttp.TCPConnector(
                limit=self.pool_limit,
                limit_per_host=self.pool_limit_per_host,
                ttl_dns_cache=300,
                enable_cleanup_closed=True,
            )
            self._session = aiohttp.ClientSession(
                timeout=timeout,
                connector=connector,
            )
        return self._session

    async def _ensure_robots(self, url: str, user_agent: str) -> None:
        """Download robots.txt once per origin, through the crawler's session."""
        origin = self.robots._origin(url)
        if origin in self.robots._cache:
            return
        async with self._robots_lock:
            if origin in self.robots._cache:
                return
            robots_url = origin + "/robots.txt"
            session = await self._get_session()
            host = SemaphoreManager._host(robots_url)
            await self.rate_limiter.acquire(host)
            try:
                async with session.get(
                    robots_url,
                    headers={"User-Agent": user_agent},
                ) as response:
                    status = response.status
                    text = await response.text()
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                logger.warning(
                    "Could not read %s [%s]; treating it as allow-all",
                    robots_url,
                    type(exc).__name__,
                )
                self.robots.store(url, 404, "")
                return
            self.robots.store(url, status, text)

    async def _next_user_agent(self) -> str:
        """Return the next User-Agent. One name stays that name."""
        async with self._agent_lock:
            agent = self.user_agents[self._agent_index % len(self.user_agents)]
            self._agent_index += 1
            return agent

    def _backoff_delay(self, attempt: int) -> float:
        """Wait after failure number attempt. attempt 0 -> factor, then double."""
        delay = self.backoff_factor * (2 ** attempt)
        if delay > self.backoff_max:
            delay = self.backoff_max
        if self.jitter > 0:
            delay += random.uniform(0, self.jitter)
        return delay

    @staticmethod
    def _should_retry(exc: BaseException) -> bool:
        if isinstance(exc, asyncio.TimeoutError):
            return True
        if isinstance(exc, aiohttp.ClientResponseError):
            return exc.status in {429, 500, 502, 503, 504}
        if isinstance(exc, aiohttp.ClientError):
            return True
        return False

    async def fetch_url(self, url: str) -> str:
        """Load a single page and return its response body as text.

        Raises
        ------
        aiohttp.ClientResponseError
            HTTP 4xx/5xx after ``raise_for_status()``.
        asyncio.TimeoutError
            Connect, read, or total timeout.
        aiohttp.ClientError
            Network-level failures (DNS, connection reset, etc.).
        """
        session = await self._get_session()
        agent = await self._next_user_agent()
        await self._ensure_robots(url, agent)
        if not self.robots.can_fetch(url, agent):
            self.blocked_urls.add(url)
            logger.warning("Blocked by robots.txt: %s [%s]", url, agent)
            raise RobotsDenied(url)
        delay = self.robots.get_crawl_delay(url, agent)
        attempt = 0
        while True:
            await self.rate_limiter.acquire(
                SemaphoreManager._host(url),
                min_interval=delay,
            )
            started = time.monotonic()
            self._request_times.append(started)
            async with self.limiter.limit(url):
                logger.info("Fetching %s", url)
                try:
                    async with session.get(url, headers={"User-Agent": agent}) as response:
                        response.raise_for_status()
                        body = await response.text()
                    logger.info("Fetched %s (%d bytes)", url, len(body))
                    return body
                except (
                    aiohttp.ClientResponseError,
                    asyncio.TimeoutError,
                    aiohttp.ClientError,
                ) as exc:
                    if isinstance(exc, aiohttp.ClientResponseError):
                        logger.warning(
                            "HTTP error fetching %s [%s]: %s",
                            url, type(exc).__name__, exc,
                        )
                    elif isinstance(exc, asyncio.TimeoutError):
                        logger.warning(
                            "Timeout fetching %s [%s]", url, type(exc).__name__,
                        )
                    else:
                        logger.warning(
                            "Network error fetching %s [%s]: %s",
                            url, type(exc).__name__, exc,
                        )
                    if attempt >= self.max_retries or not self._should_retry(exc):
                        raise
                    pause = self._backoff_delay(attempt)
                    logger.info("Retrying %s in %.2fs", url, pause)
                    attempt += 1
                finally:
                    self._requests_done += 1
            await asyncio.sleep(pause)

    async def fetch_urls(self, urls: list[str]) -> dict[str, str]:
        """Load many URLs in parallel. Returns {url: body} for successful fetches.

        Failed URLs (HTTP / timeout / network) are omitted from the result.
        Each request still respects the ``max_concurrent`` limit.
        """
        if not urls:
            return {}

        async def _safe_fetch(url: str) -> tuple[str, Optional[str]]:
            try:
                body = await self.fetch_url(url)
                return url, body
            except (aiohttp.ClientResponseError, asyncio.TimeoutError, aiohttp.ClientError,):
                return url, None

        results = await asyncio.gather(*(_safe_fetch(url) for url in urls))
        return {url: body for url, body in results if body is not None}

    async def fetch_and_parse(self, url: str) -> dict:
        """Fetch a page and parse it into the HTMLParser page dict."""
        html = await self.fetch_url(url)
        return await self.parser.parse_html(html, url)

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
        self.blocked_urls.clear()
        self._request_times.clear()
        self._requests_done = 0
        self._stats_start = time.monotonic()
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
                except (
                    aiohttp.ClientResponseError,
                    asyncio.TimeoutError,
                    aiohttp.ClientError,
                    RobotsDenied,
                ) as exc:
                    queue.mark_failed(url, f"{type(exc).__name__}: {exc}")
                    self.failed_urls[url] = f"{type(exc).__name__}: {exc}"
                self._print_progress(queue, start=start)

        workers = max(1, min(self.max_concurrent, max_pages))
        await asyncio.gather(*(worker() for _ in range(workers)))
        self._print_progress(queue, start=start)
        print(file=sys.stderr)

        return self.processed_urls

    async def close(self) -> None:
        """Close the HTTP session and its connection pool."""
        if self._session is not None and not self._session.closed:
            await self._session.close()
            self._session = None
            await asyncio.sleep(0)

    async def __aenter__(self) -> "AsyncCrawler":
        await self._get_session()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()
