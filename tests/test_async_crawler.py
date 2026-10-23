"""Unit tests for AsyncCrawler. Uses a fake ClientSession (no network)."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import aiohttp
import pytest

from crawler import AsyncCrawler


def _http_error(status: int, url: str = "https://x.test") -> aiohttp.ClientResponseError:
    request_info = MagicMock()
    request_info.real_url = url
    return aiohttp.ClientResponseError(
        request_info,
        (),
        status=status,
        message=f"HTTP {status}",
    )


class FakeResponse:
    def __init__(self, text: str, status: int = 200, url: str = "https://x.test") -> None:
        self._text = text
        self.status = status
        self._url = url

    async def text(self) -> str:
        return self._text

    def raise_for_status(self) -> None:
        if self.status >= 400:
            raise _http_error(self.status, self._url)


class FakeSession:
    def __init__(
        self,
        mapping: dict[str, FakeResponse],
        delay: float = 0.0,
        errors: dict[str, BaseException] | None = None,
    ) -> None:
        self.mapping = mapping
        self.delay = delay
        self.errors = errors or {}
        self.closed = False
        self.calls: list[str] = []
        self.inflight = 0
        self.max_inflight = 0

    def get(self, url: str) -> "_DelayedResponse":
        self.calls.append(url)
        return _DelayedResponse(self, url)

    async def close(self) -> None:
        self.closed = True


class _DelayedResponse:
    def __init__(self, session: FakeSession, url: str) -> None:
        self._session = session
        self._url = url

    async def __aenter__(self) -> FakeResponse:
        self._session.inflight += 1
        self._session.max_inflight = max(self._session.max_inflight, self._session.inflight)
        try:
            if self._session.delay:
                await asyncio.sleep(self._session.delay)
            if self._url in self._session.errors:
                raise self._session.errors[self._url]
            if self._url not in self._session.mapping:
                raise aiohttp.ClientConnectionError(f"unknown url {self._url}")
            return self._session.mapping[self._url]
        except Exception:
            self._session.inflight -= 1
            raise

    async def __aexit__(self, exc_type, exc, tb) -> None:
        self._session.inflight -= 1


@pytest.fixture
def crawler() -> AsyncCrawler:
    return AsyncCrawler(max_concurrent=2)


def test_init_rejects_non_positive() -> None:
    with pytest.raises(ValueError):
        AsyncCrawler(max_concurrent=0)


def test_init_rejects_non_positive_timeouts() -> None:
    with pytest.raises(ValueError):
        AsyncCrawler(connect_timeout=0)
    with pytest.raises(ValueError):
        AsyncCrawler(read_timeout=-1)
    with pytest.raises(ValueError):
        AsyncCrawler(pool_limit=0)


@pytest.mark.asyncio
async def test_session_uses_timeouts_and_pool() -> None:
    crawler = AsyncCrawler(
        max_concurrent=3,
        connect_timeout=1.5,
        read_timeout=2.5,
        total_timeout=4.0,
        pool_limit=20,
        pool_limit_per_host=3,
    )
    session = await crawler._get_session()
    try:
        assert isinstance(session, aiohttp.ClientSession)
        assert session.timeout.connect == 1.5
        assert session.timeout.sock_read == 2.5
        assert session.timeout.total == 4.0
        assert session.connector.limit == 20
        assert session.connector.limit_per_host == 3
    finally:
        await crawler.close()
    assert crawler._session is None
    assert session.closed is True


@pytest.mark.asyncio
async def test_fetch_url_returns_body(crawler: AsyncCrawler) -> None:
    session = FakeSession({"https://a.test": FakeResponse("hello")})
    crawler._session = session  # type: ignore[assignment]
    body = await crawler.fetch_url("https://a.test")
    assert body == "hello"
    await crawler.close()
    assert session.closed is True


@pytest.mark.asyncio
async def test_fetch_url_raises_http_error(crawler: AsyncCrawler) -> None:
    session = FakeSession({"https://bad.test": FakeResponse("nope", status=500, url="https://bad.test")})
    crawler._session = session  # type: ignore[assignment]
    with pytest.raises(aiohttp.ClientResponseError):
        await crawler.fetch_url("https://bad.test")
    await crawler.close()


@pytest.mark.asyncio
async def test_fetch_url_raises_timeout(crawler: AsyncCrawler) -> None:
    session = FakeSession({}, errors={"https://slow.test": asyncio.TimeoutError()})
    crawler._session = session  # type: ignore[assignment]
    with pytest.raises(asyncio.TimeoutError):
        await crawler.fetch_url("https://slow.test")
    await crawler.close()


@pytest.mark.asyncio
async def test_fetch_url_raises_network_error(crawler: AsyncCrawler) -> None:
    session = FakeSession({}, errors={"https://net.test": aiohttp.ClientConnectionError("reset")})
    crawler._session = session  # type: ignore[assignment]
    with pytest.raises(aiohttp.ClientError):
        await crawler.fetch_url("https://net.test")
    await crawler.close()


@pytest.mark.asyncio
async def test_fetch_urls_skips_http_timeout_and_network_errors(crawler: AsyncCrawler) -> None:
    session = FakeSession(
        {
            "https://ok.test": FakeResponse("ok"),
            "https://bad.test": FakeResponse("nope", status=500, url="https://bad.test"),
        },
        errors={
            "https://slow.test": asyncio.TimeoutError(),
            "https://net.test": aiohttp.ClientConnectionError("dns"),
        },
    )
    crawler._session = session  # type: ignore[assignment]
    result = await crawler.fetch_urls(
        [
            "https://ok.test",
            "https://bad.test",
            "https://slow.test",
            "https://net.test",
            "https://missing.test",
        ]
    )
    assert result == {"https://ok.test": "ok"}
    await crawler.close()


@pytest.mark.asyncio
async def test_fetch_urls_empty() -> None:
    crawler = AsyncCrawler()
    assert await crawler.fetch_urls([]) == {}
    await crawler.close()


@pytest.mark.asyncio
async def test_concurrency_limit() -> None:
    crawler = AsyncCrawler(max_concurrent=2)
    urls = [f"https://n{i}.test" for i in range(5)]
    session = FakeSession({u: FakeResponse("x") for u in urls}, delay=0.05)
    crawler._session = session  # type: ignore[assignment]
    await crawler.fetch_urls(urls)
    assert session.max_inflight <= 2
    await crawler.close()


@pytest.mark.asyncio
async def test_context_manager_closes_session() -> None:
    crawler = AsyncCrawler()
    session = FakeSession({})
    crawler._session = session  # type: ignore[assignment]
    async with crawler:
        assert session.closed is False
    assert session.closed is True
    assert crawler._session is None


@pytest.mark.asyncio
async def test_fetch_url_logs_start_and_success(crawler: AsyncCrawler, caplog: pytest.LogCaptureFixture) -> None:
    session = FakeSession({"https://a.test": FakeResponse("hello")})
    crawler._session = session  # type: ignore[assignment]
    with caplog.at_level("INFO", logger="crawler.async_crawler"):
        await crawler.fetch_url("https://a.test")
    messages = [record.getMessage() for record in caplog.records]
    assert any("Fetching https://a.test" in msg for msg in messages)
    assert any("Fetched https://a.test (5 bytes)" in msg for msg in messages)
    await crawler.close()


@pytest.mark.asyncio
async def test_fetch_url_logs_error_type(crawler: AsyncCrawler, caplog: pytest.LogCaptureFixture) -> None:
    session = FakeSession(
        {"https://bad.test": FakeResponse("nope", status=404, url="https://bad.test")}
    )
    crawler._session = session  # type: ignore[assignment]
    with caplog.at_level("INFO", logger="crawler.async_crawler"):
        with pytest.raises(aiohttp.ClientResponseError):
            await crawler.fetch_url("https://bad.test")
    messages = [record.getMessage() for record in caplog.records]
    assert any("Fetching https://bad.test" in msg for msg in messages)
    assert any(
        "HTTP error fetching https://bad.test [ClientResponseError]" in msg for msg in messages
    )
    await crawler.close()
