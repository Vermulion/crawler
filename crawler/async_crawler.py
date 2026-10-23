"""Base async HTTP crawler with concurrency control."""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)

# Default pool size matches aiohttp's TCPConnector.limit.
_DEFAULT_POOL_LIMIT = 100


class AsyncCrawler:
    """Fetch one or many URLs concurrently using a shared aiohttp session.

    Concurrency is limited by an asyncio.Semaphore so at most
    ``max_concurrent`` requests run at the same time.

    The shared ``aiohttp.ClientSession`` is created lazily with:
    - connect / read / total timeouts
    - a ``TCPConnector`` connection pool (keep-alive reuse)
    """

    def __init__(
        self,
        max_concurrent: int = 10,
        *,
        connect_timeout: float = 10.0,
        read_timeout: float = 30.0,
        total_timeout: float = 60.0,
        pool_limit: int = _DEFAULT_POOL_LIMIT,
        pool_limit_per_host: Optional[int] = None,
    ) -> None:
        if max_concurrent < 1:
            raise ValueError("max_concurrent must be >= 1")
        if connect_timeout <= 0 or read_timeout <= 0 or total_timeout <= 0:
            raise ValueError("timeouts must be > 0")
        if pool_limit < 1:
            raise ValueError("pool_limit must be >= 1")

        self.max_concurrent = max_concurrent
        self.connect_timeout = connect_timeout
        self.read_timeout = read_timeout
        self.total_timeout = total_timeout
        self.pool_limit = pool_limit
        self.pool_limit_per_host = (
            pool_limit_per_host if pool_limit_per_host is not None else max_concurrent
        )
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._session: Optional[aiohttp.ClientSession] = None

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
        async with self._semaphore:
            logger.info("Fetching %s", url)
            try:
                async with session.get(url) as response:
                    response.raise_for_status()
                    body = await response.text()
                logger.info("Fetched %s (%d bytes)", url, len(body))
                return body
            except aiohttp.ClientResponseError as exc:
                logger.warning(
                    "HTTP error fetching %s [%s]: %s",
                    url,
                    type(exc).__name__,
                    exc,
                )
                raise
            except asyncio.TimeoutError as exc:
                logger.warning(
                    "Timeout fetching %s [%s]",
                    url,
                    type(exc).__name__,
                )
                raise
            except aiohttp.ClientError as exc:
                logger.warning(
                    "Network error fetching %s [%s]: %s",
                    url,
                    type(exc).__name__,
                    exc,
                )
                raise

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
            except (aiohttp.ClientResponseError, asyncio.TimeoutError, aiohttp.ClientError):
                return url, None

        results = await asyncio.gather(*(_safe_fetch(url) for url in urls))
        return {url: body for url, body in results if body is not None}

    async def close(self) -> None:
        """Close the HTTP session and its connection pool."""
        if self._session is not None and not self._session.closed:
            await self._session.close()
            self._session = None
            # Let SSL transports finish so aiohttp does not warn about
            # unclosed connections.
            await asyncio.sleep(0)

    async def __aenter__(self) -> "AsyncCrawler":
        await self._get_session()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()
