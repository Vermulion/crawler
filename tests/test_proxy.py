import pytest
from crawler.async_crawler import AsyncCrawler
from tests.http_fakes import FakeResponse, FakeSession

@pytest.mark.asyncio
async def test_fetch_passes_proxy():
    session = FakeSession({"https://a.test/": FakeResponse("<html></html>", url="https://a.test/")})
    c = AsyncCrawler(respect_robots=False, proxy="http://127.0.0.1:8080")
    c._session = session
    await c.fetch_url("https://a.test/")
    assert session.request_proxies == ["http://127.0.0.1:8080"]

@pytest.mark.asyncio
async def test_fetch_without_proxy_omits_arg():
    session = FakeSession({"https://a.test/": FakeResponse("<html></html>", url="https://a.test/")})
    c = AsyncCrawler(respect_robots=False)
    c._session = session
    await c.fetch_url("https://a.test/")
    assert session.request_proxies == [None]