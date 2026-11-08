"""Unit tests for AsyncCrawler. Uses a fake ClientSession (no network)."""

from __future__ import annotations
from crawler.errors import NetworkError, PermanentError, TransientError

import asyncio

import aiohttp
import pytest

from crawler import AsyncCrawler
from tests.http_fakes import FakeResponse, FakeSession

# Keep Day-1 tests fast; politeness sleeps are covered in test_rate_limiter / test_politeness.
_FAST = dict(requests_per_second=1000.0, min_delay=0.0, jitter=0.0)


@pytest.fixture
def crawler() -> AsyncCrawler:
    return AsyncCrawler(max_concurrent=2, **_FAST)


def test_init_rejects_non_positive() -> None:
    with pytest.raises(ValueError):
        AsyncCrawler(max_concurrent=0)


def test_init_rejects_non_positive_per_domain() -> None:
    with pytest.raises(ValueError):
        AsyncCrawler(max_per_domain=0)


def test_init_rejects_non_positive_timeouts() -> None:
    with pytest.raises(ValueError):
        AsyncCrawler(connect_timeout=0)
    with pytest.raises(ValueError):
        AsyncCrawler(read_timeout=-1)
    with pytest.raises(ValueError):
        AsyncCrawler(pool_limit=0)


@pytest.mark.asyncio
async def test_session_uses_timeouts_and_pool() -> None:
    crawler =         AsyncCrawler(
        max_concurrent=3,
        requests_per_second=1000.0,
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
    with pytest.raises(TransientError):
        await crawler.fetch_url("https://bad.test")
    await crawler.close()


@pytest.mark.asyncio
async def test_fetch_url_raises_timeout(crawler: AsyncCrawler) -> None:
    session = FakeSession({}, errors={"https://slow.test": asyncio.TimeoutError()})
    crawler._session = session  # type: ignore[assignment]
    with pytest.raises(NetworkError):
        await crawler.fetch_url("https://slow.test")
    await crawler.close()


@pytest.mark.asyncio
async def test_fetch_url_raises_network_error(crawler: AsyncCrawler) -> None:
    session = FakeSession({}, errors={"https://net.test": aiohttp.ClientConnectionError("reset")})
    crawler._session = session  # type: ignore[assignment]
    with pytest.raises(NetworkError):
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
    crawler = AsyncCrawler(**_FAST)
    assert await crawler.fetch_urls([]) == {}
    await crawler.close()


@pytest.mark.asyncio
async def test_concurrency_limit() -> None:
    crawler = AsyncCrawler(max_concurrent=2, **_FAST)
    urls = [f"https://n{i}.test" for i in range(5)]
    session = FakeSession({u: FakeResponse("x") for u in urls}, delay=0.05)
    crawler._session = session  # type: ignore[assignment]
    await crawler.fetch_urls(urls)
    assert session.max_inflight <= 2
    await crawler.close()


@pytest.mark.asyncio
async def test_context_manager_closes_session() -> None:
    crawler = AsyncCrawler(**_FAST)
    session = FakeSession({})
    crawler._session = session  # type: ignore[assignment]
    async with crawler:
        assert session.closed is False
    assert session.closed is True
    assert crawler._session is None


@pytest.mark.asyncio
async def test_fetch_and_parse_uses_parser(crawler: AsyncCrawler) -> None:
    html = "<html><head><title>Hi</title></head><body><p>x</p></body></html>"
    session = FakeSession({"https://a.test": FakeResponse(html)})
    crawler._session = session  # type: ignore[assignment]
    page = await crawler.fetch_and_parse("https://a.test")
    assert page["url"] == "https://a.test"
    assert page["title"] == "Hi"
    await crawler.close()


@pytest.mark.asyncio
async def test_fetch_url_logs_start_and_success(
    crawler: AsyncCrawler, caplog: pytest.LogCaptureFixture
) -> None:
    session = FakeSession({"https://a.test": FakeResponse("hello")})
    crawler._session = session  # type: ignore[assignment]
    with caplog.at_level("INFO", logger="crawler.async_crawler"):
        await crawler.fetch_url("https://a.test")
    messages = [record.getMessage() for record in caplog.records]
    assert any("Fetching https://a.test" in msg for msg in messages)
    assert any("Fetched https://a.test (5 bytes)" in msg for msg in messages)
    await crawler.close()


@pytest.mark.asyncio
async def test_fetch_url_logs_error_type(
    crawler: AsyncCrawler, caplog: pytest.LogCaptureFixture
) -> None:
    session = FakeSession(
        {"https://bad.test": FakeResponse("nope", status=404, url="https://bad.test")}
    )
    crawler._session = session  # type: ignore[assignment]:
    with pytest.raises(PermanentError):
        await crawler.fetch_url("https://bad.test")
    messages = [record.getMessage() for record in caplog.records]
    assert any("PermanentError" in msg for msg in messages)
    await crawler.close()
