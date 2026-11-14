from __future__ import annotations

import pytest

from crawler.crawler_stats import CrawlerStats
from tests.http_fakes import FakeResponse, FakeSession, http_error
from tests.test_crawl import _crawl_with_pages, _page


@pytest.mark.asyncio
async def test_stats_after_successful_crawl() -> None:
    mapping = {
        "https://site.test/": _page("https://site.test/", "https://site.test/b"),
        "https://site.test/b": _page("https://site.test/b"),
    }
    crawler, _session = await _crawl_with_pages(
        mapping, ["https://site.test/"], max_depth=1
    )
    stats = crawler.get_crawler_stats()
    assert stats["pages_processed"] == 2
    assert stats["successful_requests"] == 2
    assert stats["failed_requests"] == 0
    assert stats["status_codes"][200] == 2
    assert stats["top_domains"][0] == ("site.test", 2)
    assert stats["elapsed_seconds"] >= 0
    assert stats["avg_pages_per_second"] >= 0
    await crawler.close()


@pytest.mark.asyncio
async def test_stats_counts_failed_status() -> None:
    mapping = {
        "https://ok.test/": _page("https://ok.test/"),
        "https://bad.test/missing": FakeResponse(
            "nope", status=404, url="https://bad.test/missing"
        ),
    }
    crawler, _session = await _crawl_with_pages(
        mapping,
        ["https://ok.test/", "https://bad.test/missing"],
        max_depth=0,
        same_domain_only=False,
    )
    stats = crawler.get_crawler_stats()
    assert stats["pages_processed"] == 1
    assert stats["failed_requests"] == 1
    assert stats["status_codes"][200] == 1
    assert stats["status_codes"][404] == 1
    hosts = dict(stats["top_domains"])
    assert hosts["ok.test"] == 1
    await crawler.close()


def test_stats_empty_crawler() -> None:
    from crawler import AsyncCrawler

    crawler = AsyncCrawler(requests_per_second=1000.0, min_delay=0.0, jitter=0.0)
    stats = CrawlerStats(crawler).summary()
    assert stats["pages_processed"] == 0
    assert stats["failed_requests"] == 0
    assert stats["status_codes"] == {}
    assert stats["top_domains"] == []