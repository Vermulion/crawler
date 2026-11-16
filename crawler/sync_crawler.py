"""Sequential crawler for speed comparison (no aiohttp)."""

from __future__ import annotations

from collections import deque
from typing import Callable

from crawler.html_parser import HTMLParser


class SyncCrawler:
    def __init__(self, get_html: Callable[[str], str]) -> None:
        self.get_html = get_html  # you pass a function: url -> html string
        self.parser = HTMLParser()
        self.processed_urls: dict[str, dict] = {}

    def crawl(self, start_urls: list[str], max_pages: int = 100) -> dict[str, dict]:
        q: deque[str] = deque(start_urls)
        seen: set[str] = set()
        self.processed_urls.clear()
        while q and len(self.processed_urls) < max_pages:
            url = q.popleft()
            if url in seen:
                continue
            seen.add(url)
            html = self.get_html(url)
            page = self.parser.parse_html_sync(html, url)
            self.processed_urls[url] = page
            for link in page.get("links") or []:
                q.append(link)
        return self.processed_urls