from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, Optional, TypeVar

import aiohttp

T = TypeVar("T")

_RETRY_HTTP = {429, 500, 502, 503, 504}


class RetryStrategy:
    """Run an async function again after temporary errors."""

    def __init__(
        self,
        max_retries: int = 3,
        backoff_factor: float = 2.0,
        retry_on: Optional[list] = None,
        backoff_max: float = 30.0,
    ) -> None:
        if max_retries < 0:
            raise ValueError("max_retries must be >= 0")
        if backoff_factor <= 0:
            raise ValueError("backoff_factor must be > 0")
        if backoff_max <= 0:
            raise ValueError("backoff_max must be > 0")

        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self.backoff_max = backoff_max
        self.retry_on: tuple[type[BaseException], ...] = tuple(
            retry_on
            if retry_on is not None
            else (asyncio.TimeoutError, aiohttp.ClientError)
        )

    def _delay(self, attempt: int) -> float:
        delay = self.backoff_factor * (2 ** attempt)
        return min(delay, self.backoff_max)

    def should_retry(self, exc: BaseException) -> bool:
        if isinstance(exc, aiohttp.ClientResponseError):
            return exc.status in _RETRY_HTTP
        return isinstance(exc, self.retry_on)

    async def execute_with_retry(
        self,
        fn: Callable[..., Awaitable[T]],
        *args,
        **kwargs,
    ) -> T:
        attempt = 0
        while True:
            try:
                return await fn(*args, **kwargs)
            except Exception as exc:
                if attempt >= self.max_retries or not self.should_retry(exc):
                    raise
                await asyncio.sleep(self._delay(attempt))
                attempt += 1