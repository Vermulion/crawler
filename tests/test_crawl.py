"""Offline crawl tests: depth limit, filters, unique visited_urls."""

from __future__ import annotations

import pytest

from crawler import AsyncCrawler
from tests.http_fakes import FakeResponse, FakeSession


def _page(url: str, *hrefs: str) -> FakeResponse:
    anchors = "".join(f'<a href="{href}">{href}</a>' for href in hrefs)
    html = f"<html><head><title>{url}</title></head><body>{anchors}</body></html>"
    return FakeResponse(html, url=url)


async def _crawl_with_pages(
    mapping: dict[str, FakeResponse],
    start: list[str],
    *,
    max_pages: int = 20,
    max_depth: int | None = None,
    **crawler_kw,
) -> tuple[AsyncCrawler, FakeSession]:
    crawler = AsyncCrawler(max_concurrent=2, **crawler_kw)
    session = FakeSession(mapping)
    crawler._session = session  # type: ignore[assignment]
    await crawler.crawl(start, max_pages=max_pages, max_depth=max_depth)
    return crawler, session


@pytest.mark.asyncio
async def test_max_depth_does_not_follow_too_deep() -> None:
    mapping = {
        "https://site.test/": _page("https://site.test/", "https://site.test/b"),
        "https://site.test/b": _page("https://site.test/b", "https://site.test/c"),
        "https://site.test/c": _page("https://site.test/c"),
    }
    crawler, session = await _crawl_with_pages(
        mapping, ["https://site.test/"], max_depth=1
    )
    assert "https://site.test/" in crawler.processed_urls
    assert "https://site.test/b" in crawler.processed_urls
    assert "https://site.test/c" not in crawler.processed_urls
    assert "https://site.test/c" not in crawler.visited_urls
    assert "https://site.test/c" not in session.calls
    await crawler.close()


@pytest.mark.asyncio
async def test_visited_urls_has_no_duplicates() -> None:
    mapping = {
        "https://site.test/": _page(
            "https://site.test/",
            "https://site.test/b",
            "https://site.test/b",
            "https://site.test/",
        ),
        "https://site.test/b": _page("https://site.test/b", "https://site.test/"),
    }
    crawler, session = await _crawl_with_pages(
        mapping,
        ["https://site.test/", "https://site.test/"],
        max_depth=2,
    )
    assert len(crawler.visited_urls) == len(set(crawler.visited_urls))
    assert session.calls.count("https://site.test/") == 1
    assert session.calls.count("https://site.test/b") == 1
    await crawler.close()


@pytest.mark.asyncio
async def test_crawl_respects_exclude_blacklist() -> None:
    mapping = {
        "https://site.test/": _page(
            "https://site.test/",
            "https://site.test/ok",
            "https://site.test/secret.pdf",
        ),
        "https://site.test/ok": _page("https://site.test/ok"),
        "https://site.test/secret.pdf": _page("https://site.test/secret.pdf"),
    }
    crawler, _session = await _crawl_with_pages(
        mapping,
        ["https://site.test/"],
        max_depth=1,
        exclude_patterns=[r"\.pdf$"],
    )
    assert "https://site.test/ok" in crawler.processed_urls
    assert "https://site.test/secret.pdf" not in crawler.visited_urls
    assert "https://site.test/secret.pdf" not in crawler.processed_urls
    await crawler.close()


@pytest.mark.asyncio
async def test_crawl_respects_include_whitelist() -> None:
    mapping = {
        "https://site.test/blog": _page(
            "https://site.test/blog",
            "https://site.test/blog/post",
            "https://site.test/about",
        ),
        "https://site.test/blog/post": _page("https://site.test/blog/post"),
        "https://site.test/about": _page("https://site.test/about"),
    }
    crawler, _session = await _crawl_with_pages(
        mapping,
        ["https://site.test/blog"],
        max_depth=1,
        include_patterns=[r"/blog"],
    )
    assert "https://site.test/blog" in crawler.processed_urls
    assert "https://site.test/blog/post" in crawler.processed_urls
    assert "https://site.test/about" not in crawler.visited_urls
    await crawler.close()
