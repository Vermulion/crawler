from __future__ import annotations

from typing import Protocol

class JsRenderer(Protocol):
    async def render(self, url: str, *, timeout: float = 30.0) -> str:
        """Return HTML after JavaScript has run."""
        ...

class PlaywrightRenderer:
    def __init__(self, *, headless: bool = True) -> None:
        self.headless = headless
        self._playwright = None
        self._browser = None

    async def start(self) -> None:
        from playwright.async_api import async_playwright  # lazy import
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=self.headless)

    async def render(self, url: str, *, timeout: float = 30.0) -> str:
        if self._browser is None:
            await self.start()
        page = await self._browser.new_page()
        try:
            await page.goto(url, wait_until="networkidle", timeout=int(timeout * 1000))
            return await page.content()
        finally:
            await page.close()

    async def close(self) -> None:
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None