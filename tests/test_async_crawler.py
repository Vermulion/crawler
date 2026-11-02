"""Unit tests for AsyncCrawler. Uses a fake ClientSession (no network)."""

from __future__ import annotations

import asyncio

import aiohttp
import pytest

from crawler import AsyncCrawler
from tests.http_fakes import FakeResponse, FakeSession


@pytest.fixture
def crawler() -> AsyncCrawler:
    return AsyncCrawler(max_concurrent=2)


def test_init_rejects_non_positive() -> None:
    with pytest.raises(ValueError):
        AsyncCrawler(max_concurrent=0)


def test_init_rejects_non_positive_per_domain() -> None:
    with pytest.raises(ValueError):
        AsyncCrawler(max_per_domain=0)


@pytest.mark.asyncio
async def test_session_is_created_and_closed() -> None:
    crawler = AsyncCrawler(max_concurrent=3)
    session = await crawler._get_session()
    try:
        assert isinstance(session, aiohttp.ClientSession)
        assert session.closed is False
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
async def test_fetch_and_parse_uses_parser(crawler: AsyncCrawler) -> None:
    html = "<html><head><title>Hi</title></head><body><p>x</p></body></html>"
    session = FakeSession({"https://a.test": FakeResponse(html)})
    crawler._session = session  # type: ignore[assignment]
    page = await crawler.fetch_and_parse("https://a.test")
    assert page["url"] == "https://a.test"
    assert page["title"] == "Hi"
    await crawler.close()
