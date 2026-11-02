"""Live crawl demo: start URLs, depth limit, progress, save JSON."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from crawler import AsyncCrawler

START_URLS = [
    "https://example.com",
    "https://www.python.org",
    "https://crawler-test.com/",
]
OUT_PATH = Path("crawl_results.json")


def page_to_json(page: dict) -> dict:
    """Keep JSON-friendly fields (drop huge raw HTML-only noise if any)."""
    return {
        "url": page.get("url", ""),
        "title": page.get("title", ""),
        "text": page.get("text", ""),
        "links": page.get("links") or [],
        "metadata": page.get("metadata") or {},
        "images": page.get("images") or [],
        "headings": page.get("headings") or [],
        "tables": page.get("tables") or [],
        "lists": page.get("lists") or [],
    }


async def main() -> None:
    async with AsyncCrawler(
        max_concurrent=10,
        same_domain_only=True,
    ) as crawler:
        results = await crawler.crawl(
            start_urls=START_URLS,
            max_pages=50,
            max_depth=2,
        )
        payload = {
            "start_urls": START_URLS,
            "processed_count": len(results),
            "failed_count": len(crawler.failed_urls),
            "visited_count": len(crawler.visited_urls),
            "processed": {url: page_to_json(page) for url, page in results.items()},
            "failed": crawler.failed_urls,
            "visited": sorted(crawler.visited_urls),
        }

    OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Обработано: {len(results)} страниц")
    print(f"Saved: {OUT_PATH.resolve()}")


if __name__ == "__main__":
    asyncio.run(main())