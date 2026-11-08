from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, Optional, TypeVar

from crawler.errors import TransientError

T = TypeVar("T")

logger = logging.getLogger(__name__)


class RetryStrategy:
    """Run an async function again after temporary errors."""

    def __init__(
        self,
        max_retries: int = 3,
        backoff_factor: float = 2.0,
        retry_on: Optional[list] = None,
        backoff_max: float = 30.0,
        max_retries_500: int = 1,
        retry_429_factor: float = 2.0,
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
            retry_on if retry_on is not None else (TransientError,)
        )
        self.max_retries_500 = max_retries_500
        self.retry_429_factor = retry_429_factor


    def extra_retries_for(self, exc: BaseException) -> int:
        """How many extra tries this error is allowed."""
        if getattr(exc, "status", None) == 500:
            return min(self.max_retries, self.max_retries_500)
        return self.max_retries


    def _delay(self, attempt: int, exc: BaseException | None = None) -> float:
        delay = self.backoff_factor * (2**attempt)
        if getattr(exc, "status", None) == 429:
            delay *= self.retry_429_factor
        return min(delay, self.backoff_max)


    def should_retry(self, exc: BaseException) -> bool:
        status = getattr(exc, "status", None)
        if status in {401, 403, 404}:
            return False
        if status in {429, 500, 503}:
            return True
        return isinstance(exc, self.retry_on)

    async def execute_with_retry(
        self,
        fn: Callable[..., Awaitable[T]],
        *args,
        **kwargs,
    ) -> T:
        attempt = 0
        total = self.max_retries + 1
        while True:
            logger.info(
                "try %d/%d of %s", attempt + 1, total, getattr(fn, "__name__", fn)
            )
            try:
                result = await fn(*args, **kwargs)
                if attempt:
                    logger.info("succeeded on try %d/%d", attempt + 1, total)
                return result
            except Exception as exc:
                if attempt >= self.extra_retries_for(exc) or not self.should_retry(exc):
                    raise
                await asyncio.sleep(self._delay(attempt, exc))
                attempt += 1