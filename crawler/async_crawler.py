"""Base async HTTP crawler with concurrency control."""

from __future__ import annotations

import asyncio
import logging
import sys
import time
from typing import Optional
from collections import Counter
from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING

import aiohttp

from crawler.crawler_queue import CrawlerQueue
from crawler.html_parser import HTMLParser
from crawler.semaphore_manager import SemaphoreManager
from crawler.url_filter import URLFilter
from crawler.rate_limiter import RateLimiter
from crawler.robots_parser import RobotsDenied, RobotsParser
from crawler.circuit_breaker import CircuitBreaker
from crawler.errors import CrawlerError, TransientError, classify_exception, CircuitOpenError
from crawler.retry_strategy import RetryStrategy
from crawler.storage import DataStorage

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
        timeout_backoff_factor: float = 2.0,
        timeout_max: float = 120.0,
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
        retry_strategy: Optional[RetryStrategy] = None,
        circuit_breaker: Optional[CircuitBreaker] = None,
        failure_threshold: int = 5,
        failure_window: float = 60.0,
        recovery_timeout: float = 30.0,
        user_agent: str = "AsyncCrawler",
        user_agents: Optional[list[str]] = None,
        storage: Optional[DataStorage] = None,
        storage_batch_size: int = 1,
        storage_max_retries: int = 2,
        storage_backoff_factor: float = 0.5,
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
        if timeout_backoff_factor <= 0:
            raise ValueError("timeout_backoff_factor must be > 0")
        if timeout_max <= 0:
            raise ValueError("timeout_max must be > 0")
        self.timeout_backoff_factor = timeout_backoff_factor
        self.timeout_max = timeout_max
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
        self.retry_strategy = retry_strategy or RetryStrategy(
            max_retries=max_retries,
            backoff_factor=backoff_factor,
            backoff_max=backoff_max,
            retry_on=[TransientError],
        )
        self.circuit_breaker = circuit_breaker or CircuitBreaker(
            failure_threshold=failure_threshold,
            failure_window=failure_window,
            recovery_timeout=recovery_timeout,
        )
        self.error_log: list[dict] = []
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
        if storage_batch_size < 1:
            raise ValueError("storage_batch_size must be >= 1")
        self.storage = storage
        self.storage_batch_size = storage_batch_size
        self._storage_buffer: list[dict] = []
        self._storage_lock = asyncio.Lock()
        if storage_max_retries < 0:
            raise ValueError("storage_max_retries must be >= 0")
        self.storage_max_retries = storage_max_retries
        self.storage_backoff_factor = storage_backoff_factor
        self.storage_errors: list[dict] = []

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

    def get_error_stats(self) -> dict:
        """Summaries from error_log: types, recovered retries, wait, 4xx URLs."""
        by_type: Counter[str] = Counter()
        waits: list[float] = []
        permanent: set[str] = set()
        recovered = 0
        for row in self.error_log:
            name = row.get("error")
            if name:
                by_type[name] += 1
            if row.get("result") == "success":
                recovered += 1
            wait = row.get("retry_in")
            if wait is not None:
                waits.append(wait)
            if name == "PermanentError":
                permanent.add(row["url"])
        avg_retry = sum(waits) / len(waits) if waits else 0.0
        return {
            "by_type": dict(by_type),
            "successful_retries": recovered,
            "avg_retry_time": avg_retry,
            "permanent_error_urls": sorted(permanent),
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

    def _timeout_for_attempt(self, attempt: int) -> aiohttp.ClientTimeout:
        """attempt 0 = base timeouts; each retry multiplies, then caps."""
        grow = self.timeout_backoff_factor ** attempt
        connect = min(self.connect_timeout * grow, self.timeout_max)
        read = min(self.read_timeout * grow, self.timeout_max)
        total = min(self.total_timeout * grow, self.timeout_max)
        total = max(total, connect, read)
        return aiohttp.ClientTimeout(total=total, connect=connect, sock_read=read)

    def _record(
        self,
        url: str,
        *,
        error: str | None,
        attempt: int,
        retry: bool,
        retry_in: float | None,
        result: str,
        status: int | None = None,
        message: str = "",
    ) -> None:
        row = {
            "url": url,
            "error": error,
            "attempt": attempt,
            "retry": retry,
            "retry_in": retry_in,
            "result": result,
            "status": status,
            "message": message,
        }
        self.error_log.append(row)
        log = logger.info if result == "success" else logger.warning
        log(
            "url=%s error=%s attempt=%s retry_in=%s result=%s",
            url,
            error,
            attempt,
            retry_in,
            result,
        )
    async def _fetch_document(self, url: str) -> str:
        """Load a single page and return its response body as text.

        Raises
        ------
        TransientError
            Retryable HTTP (429, 5xx) after retries are used up.
        NetworkError
            Timeout or connection failure after retries are used up.
        PermanentError
            HTTP 401 / 403 / 404 (and other 4xx). Not retried.
        RobotsDenied
            URL is disallowed by robots.txt.
        """
        session = await self._get_session()
        agent = await self._next_user_agent()
        await self._ensure_robots(url, agent)
        if not self.robots.can_fetch(url, agent):
            self.blocked_urls.add(url)
            logger.warning("Blocked by robots.txt: %s [%s]", url, agent)
            raise RobotsDenied(url)
        delay = self.robots.get_crawl_delay(url, agent)
        host = SemaphoreManager._host(url)
        if not self.circuit_breaker.allow(host):
            logger.warning("Circuit open for %s; skipping %s", host, url)
            err = CircuitOpenError(f"circuit open for {host}", url=url)
            self.failed_urls[url] = f"{type(err).__name__}: {err}"
            self._record(
                url,
                error="CircuitOpenError",
                attempt=0,
                retry=False,
                retry_in=None,
                result="failure",
                message=str(err),
            )
            raise err
        tries = {"n": 0}

        async def _get_body() -> tuple[str, int, str]:
            tries["n"] += 1
            await self.rate_limiter.acquire(
                SemaphoreManager._host(url),
                min_interval=delay,
            )
            started = time.monotonic()
            self._request_times.append(started)
            async with self.limiter.limit(url):
                n = tries["n"]
                total = self.retry_strategy.max_retries + 1
                try:
                    timeout = self._timeout_for_attempt(n - 1)
                    logger.info(
                        "Fetching %s (try %d/%d) timeout=%.1fs",
                        url, n, total, timeout.total or 0.0,
                    )
                    async with session.get(
                        url,
                        headers={"User-Agent": agent},
                        timeout=timeout,
                    ) as response:
                        response.raise_for_status()
                        body = await response.text()
                        status = response.status
                        headers = getattr(response, "headers", None) or {}
                        content_type = ""
                        if hasattr(headers, "get"):
                            content_type = (
                                headers.get("Content-Type")
                                or headers.get("content-type")
                                or ""
                            )
                    logger.info("Fetched %s (%d bytes) on try %d", url, len(body), n)
                    return body, status, content_type
                except (
                    aiohttp.ClientResponseError,
                    asyncio.TimeoutError,
                    aiohttp.ClientError,
                ) as exc:
                    err = classify_exception(exc, url)
                    will_retry = n <= self.retry_strategy.extra_retries_for(
                        err
                    ) and self.retry_strategy.should_retry(err)
                    retry_in = (
                        self.retry_strategy._delay(n - 1, err) if will_retry else None
                    )
                    self._record(
                        url,
                        error=type(err).__name__,
                        attempt=n,
                        retry=will_retry,
                        retry_in=retry_in,
                        result="retry" if will_retry else "failure",
                        status=err.status,
                        message=str(err),
                    )
                    raise err
                finally:
                    self._requests_done += 1

        try:
            body, status, content_type = await self.retry_strategy.execute_with_retry(
                _get_body
            )
        except TransientError as exc:
            self.circuit_breaker.record_failure(host)
            self.failed_urls[url] = f"{type(exc).__name__}: {exc}"
            raise
        except CrawlerError as exc:
            self.failed_urls[url] = f"{type(exc).__name__}: {exc}"
            raise
        self.circuit_breaker.record_success(host)
        if any(row["url"] == url and row["result"] == "retry" for row in self.error_log):
            self._record(
                url,
                error=None,
                attempt=tries["n"],
                retry=False,
                retry_in=None,
                result="success",
            )
        return body, status, content_type

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
            except (CrawlerError, RobotsDenied):
                return url, None

        results = await asyncio.gather(*(_safe_fetch(url) for url in urls))
        return {url: body for url, body in results if body is not None}

    async def fetch_url(self, url: str) -> str:
        body, _status, _content_type = await self._fetch_document(url)
        return body

    async def fetch_and_parse(self, url: str) -> dict:
        html, status, content_type = await self._fetch_document(url)
        page = await self.parser.parse_html(html, url)
        page["status_code"] = status
        page["content_type"] = content_type
        page["crawled_at"] = datetime.now(timezone.utc)
        return page

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
        self.storage_errors.clear()
        self.processed_urls.clear()
        self.error_log.clear()
        self.circuit_breaker = CircuitBreaker(
            failure_threshold=self.circuit_breaker.failure_threshold,
            failure_window=self.circuit_breaker.failure_window,
            recovery_timeout=self.circuit_breaker.recovery_timeout,
        )

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
                    await self._enqueue_storage(page)
                    for link in page.get("links") or []:
                        queue.add_url(link, depth=depth + 1)
                except (CrawlerError, RobotsDenied) as exc:
                    queue.mark_failed(url, f"{type(exc).__name__}: {exc}")
                    self.failed_urls[url] = f"{type(exc).__name__}: {exc}"
                self._print_progress(queue, start=start)

        workers = max(1, min(self.max_concurrent, max_pages))
        await asyncio.gather(*(worker() for _ in range(workers)))
        await self._flush_storage()
        self._print_progress(queue, start=start)
        print(file=sys.stderr)

        return self.processed_urls

    async def _enqueue_storage(self, page: dict) -> None:
        if self.storage is None:
            return
        to_flush: list[dict] | None = None
        async with self._storage_lock:
            self._storage_buffer.append(page)
            if len(self._storage_buffer) >= self.storage_batch_size:
                to_flush = self._storage_buffer
                self._storage_buffer = []
        if to_flush:
            await self._save_with_retry(to_flush)

    async def _flush_storage(self) -> None:
        if self.storage is None:
            return
        async with self._storage_lock:
            to_flush = self._storage_buffer
            self._storage_buffer = []
        if to_flush:
            await self._save_with_retry(to_flush)

    async def _save_with_retry(self, rows: list[dict]) -> None:
        """Retry save_many. Log failures. Never raise — crawl must continue."""
        if self.storage is None:
            return
        total = self.storage_max_retries + 1
        last_exc: BaseException | None = None
        for attempt in range(total):
            try:
                await self.storage.save_many(rows)
                if attempt:
                    logger.info(
                        "Storage save succeeded on try %d/%d (%d pages)",
                        attempt + 1,
                        total,
                        len(rows),
                    )
                return
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "Storage save failed try %d/%d [%s]: %s",
                    attempt + 1,
                    total,
                    type(exc).__name__,
                    exc,
                )
                if attempt + 1 >= total:
                    break
                delay = self.storage_backoff_factor * (2 ** attempt)
                await asyncio.sleep(delay)
        logger.error(
            "Storage save gave up after %d tries [%s]: %s (pages=%d)",
            total,
            type(last_exc).__name__,
            last_exc,
            len(rows),
        )
        self.storage_errors.append(
            {
                "error": type(last_exc).__name__,
                "message": str(last_exc),
                "pages": len(rows),
                "urls": [row.get("url", "") for row in rows],
            }
        )

    async def close(self) -> None:
        """Close the HTTP session and its connection pool."""
        await self._flush_storage()
        if self._session is not None and not self._session.closed:
            await self._session.close()
            self._session = None
            await asyncio.sleep(0)

    async def __aenter__(self) -> "AsyncCrawler":
        await self._get_session()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()
