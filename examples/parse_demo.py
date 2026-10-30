"""Demo: fetch several pages, parse them, print structured stats.

Shows absolute same-host links, headings, and compact page statistics.
"""

from __future__ import annotations

import asyncio
import json
import logging

from crawler import AsyncCrawler

URLS = [
    "https://example.com",
    "https://www.python.org",
    "https://httpbin.org/html",
]


def summarize(page: dict) -> dict:
    return {
        "url": page.get("url", ""),
        "title": page.get("title", ""),
        "text_length": len(page.get("text") or ""),
        "links_count": len(page.get("links") or []),
        "links": page.get("links") or [],
        "images_count": len(page.get("images") or []),
        "headings": page.get("headings") or [],
        "link_details": page.get("link_details") or [],
    }


def print_page(summary: dict) -> None:
    print(json.dumps(
        {
            "url": summary["url"],
            "title": summary["title"],
            "text_length": summary["text_length"],
            "links_count": summary["links_count"],
            "links": summary["links"][:8],
            "images_count": summary["images_count"],
        },
        indent=2,
        ensure_ascii=False,
    ))
    headings = summary["headings"][:8]
    if headings:
        print("headings:")
        for item in headings:
            print(f"  {item['level']}: {item['text']}")
    details = summary["link_details"][:8]
    if details:
        print("links (original href -> absolute):")
        for item in details:
            status = "kept" if item.get("kept") else item.get("reason", "skip")
            print(f"  [{status}] {item.get('href')} -> {item.get('absolute')}")
    print()


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    async with AsyncCrawler(max_concurrent=5) as crawler:
        pages = await asyncio.gather(
            *(crawler.fetch_and_parse(url) for url in URLS),
            return_exceptions=True,
        )

    print("=== parsed pages ===")
    for url, page in zip(URLS, pages):
        if isinstance(page, Exception):
            print(json.dumps({"url": url, "error": type(page).__name__, "message": str(page)}, indent=2))
            print()
            continue
        print_page(summarize(page))


if __name__ == "__main__":
    asyncio.run(main())
