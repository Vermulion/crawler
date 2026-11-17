import pytest
from crawler.async_crawler import AsyncCrawler

class FakeRenderer:
    def __init__(self) -> None:
        self.urls: list[str] = []

    async def render(self, url: str, *, timeout: float = 30.0) -> str:
        self.urls.append(url)
        return '<html><a href="/x">x</a></html>'

@pytest.mark.asyncio
async def test_js_render_uses_renderer_not_aiohttp():
    renderer = FakeRenderer()
    c = AsyncCrawler(respect_robots=False, js_render=True, js_renderer=renderer)
    page = await c.fetch_and_parse("https://spa.test/")
    assert renderer.urls == ["https://spa.test/"]
    assert "/x" in page["links"] or any("x" in str(x) for x in page["links"])