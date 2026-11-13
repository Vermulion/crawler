from __future__ import annotations

import pytest

from crawler.sitemap_parser import SitemapParser
from crawler import AsyncCrawler
from tests.http_fakes import FakeResponse, FakeSession
from tests.test_crawl import _page


URLSET = """\
<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://site.test/a</loc></url>
  <url><loc>https://site.test/b</loc></url>
</urlset>
"""

INDEX = """\
<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://site.test/s1.xml</loc></sitemap>
  <sitemap><loc>https://site.test/s2.xml</loc></sitemap>
</sitemapindex>
"""

NESTED_INDEX = """\
<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://site.test/sitemap.xml</loc></sitemap>
</sitemapindex>
"""

S1 = """\
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://site.test/a</loc></url>
</urlset>
"""
S2 = """\
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://site.test/b</loc></url>
  <url><loc>https://site.test/a</loc></url>
</urlset>
"""


def test_parse_urlset() -> None:
    kind, locs = SitemapParser().parse_sitemap(URLSET)
    assert kind == "urlset"
    assert locs == ["https://site.test/a", "https://site.test/b"]


def test_parse_index() -> None:
    kind, locs = SitemapParser().parse_sitemap(INDEX)
    assert kind == "index"
    assert locs == ["https://site.test/s1.xml", "https://site.test/s2.xml"]


@pytest.mark.asyncio
async def test_fetch_urlset() -> None:
    session = FakeSession(
        {"https://site.test/sitemap.xml": FakeResponse(URLSET, url="https://site.test/sitemap.xml")}
    )
    urls = await SitemapParser().fetch_sitemap(
        "https://site.test/sitemap.xml", session=session
    )
    assert urls == ["https://site.test/a", "https://site.test/b"]


@pytest.mark.asyncio
async def test_fetch_index_recurses_and_dedupes() -> None:
    session = FakeSession(
        {
            "https://site.test/sitemap.xml": FakeResponse(INDEX),
            "https://site.test/s1.xml": FakeResponse(S1),
            "https://site.test/s2.xml": FakeResponse(S2),
        }
    )
    urls = await SitemapParser().fetch_sitemap(
        "https://site.test/sitemap.xml", session=session
    )
    assert urls == ["https://site.test/a", "https://site.test/b"]
    assert session.calls == [
        "https://site.test/sitemap.xml",
        "https://site.test/s1.xml",
        "https://site.test/s2.xml",
    ]


@pytest.mark.asyncio
async def test_index_cycle_does_not_loop() -> None:
    session = FakeSession(
        {"https://site.test/sitemap.xml": FakeResponse(NESTED_INDEX)}
    )
    urls = await SitemapParser().fetch_sitemap(
        "https://site.test/sitemap.xml", session=session
    )
    assert urls == []
    assert session.calls.count("https://site.test/sitemap.xml") == 1


@pytest.mark.asyncio
async def test_crawl_uses_sitemap_seeds() -> None:
    mapping = {
        "https://site.test/sitemap.xml": FakeResponse(URLSET),
        "https://site.test/a": _page("https://site.test/a"),
        "https://site.test/b": _page("https://site.test/b"),
        "https://site.test/robots.txt": FakeResponse("User-agent: *\nAllow: /\n"),
    }
    crawler = AsyncCrawler(
        max_concurrent=2, requests_per_second=1000.0, min_delay=0.0, jitter=0.0
    )
    crawler._session = FakeSession(mapping)  # type: ignore[assignment]
    await crawler.crawl(
        [],
        max_pages=10,
        max_depth=0,
        sitemap_urls=["https://site.test/sitemap.xml"],
    )
    assert "https://site.test/a" in crawler.processed_urls
    assert "https://site.test/b" in crawler.processed_urls
    assert "https://site.test/sitemap.xml" not in crawler.processed_urls
    await crawler.close()