from __future__ import annotations

import asyncio
import aiohttp


class CrawlerError(Exception):
    """Base class for crawler errors."""

    def __init__(
        self,
        message: str = "",
        *,
        url: str = "",
        status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.url = url
        self.status = status


class TransientError(CrawlerError):
    """Temporary problem. Safe to retry."""


class PermanentError(CrawlerError):
    """Will not succeed if we try again. HTTP 401, 403, 404."""


class NetworkError(TransientError):
    """Timeout, DNS, or connection failure."""


class ParseError(CrawlerError):
    """Downloaded bytes are not usable HTML."""

class CircuitOpenError(CrawlerError):
    """This domain is temporarily blocked by the circuit breaker."""


_PERMANENT_HTTP = {401, 403, 404}
_TRANSIENT_HTTP = {408, 429, 500, 502, 503, 504}


def classify_status(status: int, url: str = "") -> CrawlerError:
    """Turn an HTTP status code into one of our error classes."""
    if status in _PERMANENT_HTTP:
        return PermanentError(f"HTTP {status} for {url}", url=url, status=status)
    if status in _TRANSIENT_HTTP:
        return TransientError(f"HTTP {status} for {url}", url=url, status=status)
    if 400 <= status < 500:
        return PermanentError(f"HTTP {status} for {url}", url=url, status=status)
    if 500 <= status < 600:
        return TransientError(f"HTTP {status} for {url}", url=url, status=status)
    return TransientError(f"HTTP {status} for {url}", url=url, status=status)


def classify_exception(exc: BaseException, url: str = "") -> CrawlerError:
    """Turn aiohttp / asyncio errors into our classes."""
    if isinstance(exc, CrawlerError):
        return exc
    if isinstance(exc, aiohttp.ClientResponseError):
        return classify_status(exc.status, url=url or str(exc.request_info.url))
    if isinstance(exc, (asyncio.TimeoutError, aiohttp.ClientError)):
        return NetworkError(f"{type(exc).__name__}: {exc}", url=url)
    return PermanentError(f"{type(exc).__name__}: {exc}", url=url)
