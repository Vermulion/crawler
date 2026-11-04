"""Crawler politeness: robots block, delay floor, per-domain vs global rate."""

from __future__ import annotations

import asyncio
import time

import pytest

from crawler import AsyncCrawler, RobotsDenied
from tests.http_fakes import FakeResponse, FakeSession

ROBOTS = """
User-agent: *
Disallow: /private
"""


def _crawler(session: FakeSession, **kwargs) -> AsyncCrawler:
    defaults = dict(
        max_concurrent=5,
        requests_per_second=100.0,
        min_delay=0.0,
        jitter=0.0,
    )
    defaults.update(kwargs)
    crawler = AsyncCrawler(**defaults)
    crawler._session = session  # type: ignore[assignment]
    return crawler


def _pages(*urls: str, robots: str = ROBOTS) -> dict[str, FakeResponse]:
    mapping: dict[str, FakeResponse] = {}
    hosts = {f"{url.split('/')[0]}//{url.split('/')[2]}" for url in urls}
    for origin in hosts:
        mapping[origin + "/robots.txt"] = FakeResponse(robots, url=origin + "/robots.txt")
    for url in urls:
        mapping[url] = FakeResponse("ok", url=url)
    return mapping


@pytest.mark.asyncio
async def test_forbidden_url_is_blocked_and_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    pages = _pages("https://a.test/ok", "https://a.test/private")
    session = FakeSession(pages)
    crawler = _crawler(session, user_agent="MyBot")
    body = await crawler.fetch_url("https://a.test/ok")
    assert body == "ok"
    with caplog.at_level("WARNING", logger="crawler.async_crawler"):
        with pytest.raises(RobotsDenied):
            await crawler.fetch_url("https://a.test/private")
    assert "https://a.test/private" in crawler.blocked_urls
    assert crawler.get_speed_stats()["blocked"] == 1
    assert session.calls.count("https://a.test/private") == 0
    messages = [record.getMessage() for record in caplog.records]
    assert any("Blocked by robots.txt: https://a.test/private" in msg for msg in messages)
    await crawler.close()


@pytest.mark.asyncio
async def test_crawl_records_forbidden_url_as_failed() -> None:
    pages = {
        "https://a.test/robots.txt": FakeResponse(ROBOTS, url="https://a.test/robots.txt"),
        "https://a.test/": FakeResponse(
            '<html><body><a href="https://a.test/private">x</a></body></html>',
            url="https://a.test/",
        ),
        "https://a.test/private": FakeResponse("secret", url="https://a.test/private"),
    }
    crawler = _crawler(FakeSession(pages), same_domain_only=True)
    results = await crawler.crawl(["https://a.test/"], max_pages=5, max_depth=1)
    assert "https://a.test/" in results
    assert "https://a.test/private" in crawler.blocked_urls
    assert "https://a.test/private" in crawler.failed_urls
    assert "RobotsDenied" in crawler.failed_urls["https://a.test/private"]
    await crawler.close()


@pytest.mark.asyncio
async def test_min_delay_is_kept_between_same_host_pages() -> None:
    pages = _pages("https://a.test/1", "https://a.test/2")
    crawler = _crawler(
        FakeSession(pages),
        requests_per_second=100.0,
        min_delay=0.2,
        jitter=0.0,
    )
    t0 = time.monotonic()
    await crawler.fetch_url("https://a.test/1")
    await crawler.fetch_url("https://a.test/2")
    elapsed = time.monotonic() - t0
    stats = crawler.get_speed_stats()
    assert stats["requests"] == 2
    assert stats["avg_delay"] == pytest.approx(0.2, abs=0.1)
    assert elapsed >= 0.35
    await crawler.close()


@pytest.mark.asyncio
async def test_rate_limit_one_domain_through_crawler() -> None:
    pages = _pages("https://a.test/1", "https://a.test/2")
    crawler = _crawler(
        FakeSession(pages),
        requests_per_second=5.0,
        min_delay=0.0,
        jitter=0.0,
    )
    t0 = time.monotonic()
    await asyncio.gather(
        crawler.fetch_url("https://a.test/1"),
        crawler.fetch_url("https://a.test/2"),
    )
    assert time.monotonic() - t0 == pytest.approx(0.4, abs=0.15)
    await crawler.close()


@pytest.mark.asyncio
async def test_rate_limit_several_domains_are_independent() -> None:
    pages = _pages("https://a.test/1", "https://b.test/1")
    crawler = _crawler(
        FakeSession(pages),
        requests_per_second=5.0,
        rate_limit_per_domain=True,
        min_delay=0.0,
        jitter=0.0,
    )
    t0 = time.monotonic()
    await asyncio.gather(
        crawler.fetch_url("https://a.test/1"),
        crawler.fetch_url("https://b.test/1"),
    )
    assert time.monotonic() - t0 < 0.35
    await crawler.close()
