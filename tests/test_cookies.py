import pytest
from crawler.async_crawler import AsyncCrawler

@pytest.mark.asyncio
async def test_session_gets_seed_cookies():
    async with AsyncCrawler(cookies={"sid": "abc"}) as c:
        session = await c._get_session()
        dumped = {cookie.key: cookie.value for cookie in session.cookie_jar}
        assert dumped.get("sid") == "abc"
    # session closed by async with