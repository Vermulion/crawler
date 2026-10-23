"""Minimal usage example for AsyncCrawler."""

import asyncio

from crawler import AsyncCrawler


async def main() -> None:
    urls = [
        "https://example.com",
        "https://example.org",
    ]
    async with AsyncCrawler(max_concurrent=5) as crawler:
        pages = await crawler.fetch_urls(urls)
        for url, body in pages.items():
            print(f"{url}: {len(body)} bytes")


if __name__ == "__main__":
    asyncio.run(main())
