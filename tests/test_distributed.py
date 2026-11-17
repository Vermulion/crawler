import pytest
from crawler.async_crawler import AsyncCrawler
from crawler.frontier import InMemoryFrontier
from tests.http_fakes import FakeResponse, FakeSession
import asyncio

@pytest.mark.asyncio
async def test_two_crawlers_share_frontier_no_duplicate_fetch():
    pages = {
        "https://a.test/": FakeResponse('<a href="https://a.test/1">1</a>', url="https://a.test/"),
        "https://a.test/1": FakeResponse("one", url="https://a.test/1"),
    }
    frontier = InMemoryFrontier(max_pages=10)
    await frontier.add("https://a.test/")
    session = FakeSession(pages)
    c1 = AsyncCrawler(respect_robots=False, max_concurrent=1)
    c2 = AsyncCrawler(respect_robots=False, max_concurrent=1)
    c1._session = session
    c2._session = session
    await asyncio.gather(c1.crawl_shared(frontier), c2.crawl_shared(frontier))
    assert session.calls.count("https://a.test/") == 1
    assert session.calls.count("https://a.test/1") == 1