"""Offline tests for CrawlerQueue: priority, depth, filters, no duplicate enqueue."""

from __future__ import annotations

import pytest

from crawler.crawler_queue import CrawlerQueue
from crawler.url_filter import URLFilter


@pytest.mark.asyncio
async def test_higher_priority_comes_out_first() -> None:
    queue = CrawlerQueue()
    queue.add_url("https://site.test/low", priority=1)
    queue.add_url("https://site.test/high", priority=10)
    queue.add_url("https://site.test/mid", priority=5)

    assert await queue.get_next() == "https://site.test/high"
    assert await queue.get_next() == "https://site.test/mid"
    assert await queue.get_next() == "https://site.test/low"
    assert await queue.get_next() is None


@pytest.mark.asyncio
async def test_same_priority_keeps_insertion_order() -> None:
    queue = CrawlerQueue()
    queue.add_url("https://site.test/a", priority=0)
    queue.add_url("https://site.test/b", priority=0)
    queue.add_url("https://site.test/c", priority=0)

    assert await queue.get_next() == "https://site.test/a"
    assert await queue.get_next() == "https://site.test/b"
    assert await queue.get_next() == "https://site.test/c"


def test_duplicate_url_is_not_queued_twice() -> None:
    queue = CrawlerQueue(["https://site.test/a", "https://site.test/a"])
    queue.add_url("https://site.test/a", priority=99)
    assert queue.get_stats()["pending"] == 1
    assert queue.get_stats()["seen"] == 1


def test_max_depth_skips_deeper_urls() -> None:
    queue = CrawlerQueue(max_depth=1)
    queue.add_url("https://site.test/", depth=0)
    queue.add_url("https://site.test/blog", depth=1)
    queue.add_url("https://site.test/blog/post", depth=2)

    assert "https://site.test/" in queue._seen
    assert "https://site.test/blog" in queue._seen
    assert "https://site.test/blog/post" not in queue._seen
    assert queue._depths["https://site.test/blog"] == 1


def test_max_pages_caps_seen() -> None:
    queue = CrawlerQueue(max_pages=2)
    queue.add_url("https://site.test/a")
    queue.add_url("https://site.test/b")
    queue.add_url("https://site.test/c")
    assert queue.get_stats()["seen"] == 2
    assert "https://site.test/c" not in queue._seen


def test_whitelist_include_patterns() -> None:
    filt = URLFilter(
        same_domain_only=False,
        include_patterns=[r"/blog"],
    )
    queue = CrawlerQueue(url_filter=filt)
    queue.add_url("https://site.test/blog/post")
    queue.add_url("https://site.test/about")
    assert "https://site.test/blog/post" in queue._seen
    assert "https://site.test/about" not in queue._seen


def test_blacklist_exclude_patterns() -> None:
    filt = URLFilter(
        same_domain_only=False,
        exclude_patterns=[r"\.pdf$", r"/login"],
    )
    queue = CrawlerQueue(url_filter=filt)
    queue.add_url("https://site.test/page")
    queue.add_url("https://site.test/file.pdf")
    queue.add_url("https://site.test/login")
    assert "https://site.test/page" in queue._seen
    assert "https://site.test/file.pdf" not in queue._seen
    assert "https://site.test/login" not in queue._seen


def test_include_and_exclude_together() -> None:
    filt = URLFilter(
        same_domain_only=False,
        include_patterns=[r"/docs/"],
        exclude_patterns=[r"\.pdf$"],
    )
    queue = CrawlerQueue(url_filter=filt)
    queue.add_url("https://site.test/docs/guide")
    queue.add_url("https://site.test/docs/guide.pdf")
    queue.add_url("https://site.test/about")
    assert queue._seen == {"https://site.test/docs/guide"}


def test_init_rejects_bad_limits() -> None:
    with pytest.raises(ValueError):
        CrawlerQueue(max_pages=0)
    with pytest.raises(ValueError):
        CrawlerQueue(max_depth=-1)
