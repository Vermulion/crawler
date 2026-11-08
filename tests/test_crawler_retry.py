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
async def test_404_and_403_are_not_retried() -> None:
    for status in (404, 403):
        url = f"https://a.test/{status}"
        session = FakeSession(
            {
                url: FakeResponse("nope", status=status, url=url),
                "https://a.test/robots.txt": FakeResponse("User-agent: *\nAllow: /"),
            }
        )
        crawler = _crawler(session, max_retries=3)
        with pytest.raises(PermanentError) as caught:
            await crawler.fetch_url(url)
        assert caught.value.status == status
        assert session.calls.count(url) == 1
        assert crawler.error_log[0]["retry"] is False
        assert crawler.error_log[0]["result"] == "failure"
        assert crawler.error_log[0]["retry_in"] is None
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

@pytest.mark.asyncio
async def test_503_retries_full_max(monkeypatch: pytest.MonkeyPatch) -> None:
    async def no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr("crawler.retry_strategy.asyncio.sleep", no_sleep)
    url = "https://a.test/down"
    session = FakeSession(
        {
            url: FakeResponse("nope", status=503, url=url),
            "https://a.test/robots.txt": FakeResponse("User-agent: *\nAllow: /"),
        }
    )
    crawler = _crawler(session, max_retries=2, backoff_factor=0.01)
    with pytest.raises(TransientError):
        await crawler.fetch_url(url)
    assert session.calls.count(url) == 3
    assert len(crawler.error_log) == 3
    assert crawler.error_log[0]["result"] == "retry"
    assert crawler.error_log[-1]["result"] == "failure"
    await crawler.close()


@pytest.mark.asyncio
async def test_500_retries_only_once(monkeypatch: pytest.MonkeyPatch) -> None:
    async def no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr("crawler.retry_strategy.asyncio.sleep", no_sleep)
    url = "https://a.test/bug"
    session = FakeSession(
        {
            url: FakeResponse("nope", status=500, url=url),
            "https://a.test/robots.txt": FakeResponse("User-agent: *\nAllow: /"),
        }
    )
    crawler = _crawler(session, max_retries=5, backoff_factor=0.01)
    with pytest.raises(TransientError):
        await crawler.fetch_url(url)
    assert session.calls.count(url) == 2
    await crawler.close()


@pytest.mark.asyncio
async def test_429_waits_longer_than_normal(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr("crawler.retry_strategy.asyncio.sleep", fake_sleep)
    url = "https://a.test/limit"
    session = FakeSession(
        {
            url: FakeResponse("nope", status=429, url=url),
            "https://a.test/robots.txt": FakeResponse("User-agent: *\nAllow: /"),
        }
    )
    crawler = _crawler(session, max_retries=1, backoff_factor=1.0)
    with pytest.raises(TransientError):
        await crawler.fetch_url(url)
    retry_sleeps = [s for s in sleeps if s >= 1.0]
    assert retry_sleeps == [2.0]
    assert len(retry_sleeps) == 1
    await crawler.close()

def test_timeout_grows_then_caps() -> None:
    crawler = AsyncCrawler(
        connect_timeout=10.0,
        read_timeout=10.0,
        total_timeout=20.0,
        timeout_backoff_factor=2.0,
        timeout_max=50.0,
        requests_per_second=1000.0,
    )
    t0 = crawler._timeout_for_attempt(0)
    t1 = crawler._timeout_for_attempt(1)
    t2 = crawler._timeout_for_attempt(5)
    assert t0.total == 20.0
    assert t1.total == 40.0
    assert t1.connect == 20.0
    assert t2.total == 50.0  # capped, not 20 * 32


@pytest.mark.asyncio
async def test_timeout_error_is_network_and_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr("crawler.retry_strategy.asyncio.sleep", no_sleep)
    url = "https://a.test/slow"
    session = FakeSession(
        {
            url: FakeResponse("ok", url=url),
            "https://a.test/robots.txt": FakeResponse("User-agent: *\nAllow: /"),
        },
        errors={url: asyncio.TimeoutError()},
    )
    crawler = _crawler(
        session,
        max_retries=2,
        backoff_factor=0.01,
        connect_timeout=1.0,
        read_timeout=1.0,
        total_timeout=2.0,
        timeout_backoff_factor=2.0,
        timeout_max=20.0,
    )
    with pytest.raises(NetworkError):
        await crawler.fetch_url(url)
    assert session.calls.count(url) == 3
    page_timeouts = [
        t.total for t, u in zip(session.request_timeouts, session.calls)
        if u == url and t is not None
    ]
    assert page_timeouts[0] == 2.0
    assert page_timeouts[1] == 4.0
    assert page_timeouts[2] == 8.0
    assert crawler.error_log[0]["error"] == "NetworkError"
    assert crawler.error_log[-1]["result"] == "failure"
    assert crawler.error_log[-1]["retry_in"] is None
    assert crawler.error_log[0]["retry_in"] == pytest.approx(0.01)
    assert crawler.error_log[0]["result"] == "retry"
    await crawler.close()


@pytest.mark.asyncio
async def test_exponential_backoff_on_503(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr("crawler.retry_strategy.asyncio.sleep", fake_sleep)
    url = "https://a.test/down"
    session = FakeSession(
        {
            url: FakeResponse("nope", status=503, url=url),
            "https://a.test/robots.txt": FakeResponse("User-agent: *\nAllow: /"),
        }
    )
    crawler = _crawler(session, max_retries=3, backoff_factor=2.0)
    with pytest.raises(TransientError):
        await crawler.fetch_url(url)
    retry_sleeps = [s for s in sleeps if s >= 1.0]
    assert retry_sleeps == [2.0, 4.0, 8.0]
    assert session.calls.count(url) == 4
    await crawler.close()

@pytest.mark.asyncio
async def test_error_log_has_delay_and_final_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr("crawler.retry_strategy.asyncio.sleep", no_sleep)
    url = "https://a.test/flaky"
    session = FakeSession(
        {
            url: FakeResponse("ok", url=url),
            "https://a.test/robots.txt": FakeResponse("User-agent: *\nAllow: /"),
        },
        errors={url: asyncio.TimeoutError()},
        fail_counts={url: 2},
    )
    crawler = _crawler(session, max_retries=3, backoff_factor=2.0)
    body = await crawler.fetch_url(url)
    assert body == "ok"
    rows = [r for r in crawler.error_log if r["url"] == url]
    assert rows[0]["error"] == "NetworkError"
    assert rows[0]["attempt"] == 1
    assert rows[0]["retry_in"] == 2.0
    assert rows[0]["result"] == "retry"
    assert rows[1]["attempt"] == 2
    assert rows[1]["retry_in"] == 4.0
    assert rows[1]["result"] == "retry"
    assert rows[2]["result"] == "success"
    assert rows[2]["retry_in"] is None
    assert rows[2]["error"] is None
    await crawler.close()

@pytest.mark.asyncio
async def test_error_stats(monkeypatch: pytest.MonkeyPatch) -> None:
    async def no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr("crawler.retry_strategy.asyncio.sleep", no_sleep)
    flaky = "https://a.test/flaky"
    missing = "https://a.test/missing"
    session = FakeSession(
        {
            flaky: FakeResponse("ok", url=flaky),
            missing: FakeResponse("nope", status=404, url=missing),
            "https://a.test/robots.txt": FakeResponse("User-agent: *\nAllow: /"),
        },
        errors={flaky: asyncio.TimeoutError()},
        fail_counts={flaky: 2},
    )
    crawler = _crawler(session, max_retries=3, backoff_factor=2.0)
    assert await crawler.fetch_url(flaky) == "ok"
    with pytest.raises(PermanentError):
        await crawler.fetch_url(missing)

    stats = crawler.get_error_stats()
    assert stats["by_type"]["NetworkError"] == 2
    assert stats["by_type"]["PermanentError"] == 1
    assert stats["successful_retries"] == 1
    assert stats["avg_retry_time"] == 3.0  # (2.0 + 4.0) / 2
    assert stats["permanent_error_urls"] == [missing]
    await crawler.close()


def test_error_stats_empty() -> None:
    crawler = AsyncCrawler(requests_per_second=1000.0)
    assert crawler.get_error_stats() == {
        "by_type": {},
        "successful_retries": 0,
        "avg_retry_time": 0.0,
        "permanent_error_urls": [],
    }