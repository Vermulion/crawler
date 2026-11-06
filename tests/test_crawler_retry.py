from __future__ import annotations

import asyncio

import pytest

from crawler import AsyncCrawler
from crawler.errors import NetworkError, PermanentError, TransientError
from crawler.retry_strategy import RetryStrategy
from tests.http_fakes import FakeResponse, FakeSession


def _crawler(session: FakeSession, **kwargs) -> AsyncCrawler:
    crawler = AsyncCrawler(
        requests_per_second=1000.0,
        min_delay=0.0,
        jitter=0.0,
        **kwargs,
    )
    crawler._session = session  # type: ignore[assignment]
    return crawler


@pytest.mark.asyncio
async def test_retries_timeout_then_saves_error_log(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr("crawler.retry_strategy.asyncio.sleep", no_sleep)

    url = "https://a.test/slow"
    session = FakeSession(
        {url: FakeResponse("ok", url=url), "https://a.test/robots.txt": FakeResponse("User-agent: *\nAllow: /")},
        errors={url: asyncio.TimeoutError()},
    )
    crawler = _crawler(session, max_retries=2, backoff_factor=0.01)
    with pytest.raises(NetworkError):
        await crawler.fetch_url(url)

    assert session.calls.count(url) == 3
    assert len(crawler.error_log) == 3
    assert crawler.error_log[0]["retry"] is True
    assert crawler.error_log[-1]["retry"] is False
    assert "NetworkError" in crawler.failed_urls[url]
    await crawler.close()


@pytest.mark.asyncio
async def test_404_is_not_retried() -> None:
    url = "https://a.test/missing"
    session = FakeSession(
        {
            url: FakeResponse("nope", status=404, url=url),
            "https://a.test/robots.txt": FakeResponse("User-agent: *\nAllow: /"),
        }
    )
    crawler = _crawler(session, max_retries=3)
    with pytest.raises(PermanentError):
        await crawler.fetch_url(url)
    assert session.calls.count(url) == 1
    assert crawler.error_log[0]["retry"] is False
    await crawler.close()


@pytest.mark.asyncio
async def test_custom_retry_strategy_instance() -> None:
    url = "https://a.test/x"
    session = FakeSession(
        {
            url: FakeResponse("nope", status=503, url=url),
            "https://a.test/robots.txt": FakeResponse("User-agent: *\nAllow: /"),
        }
    )
    crawler = _crawler(
        session,
        retry_strategy=RetryStrategy(max_retries=0, retry_on=[TransientError]),
    )
    with pytest.raises(TransientError):
        await crawler.fetch_url(url)
    assert session.calls.count(url) == 1
    assert crawler.retry_strategy.max_retries == 0
    await crawler.close()