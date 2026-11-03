# crawler

Async HTTP crawler on **aiohttp**. It fetches pages in parallel with a global
and per-domain concurrency cap, follows same-host links through a priority
queue, filters URLs, and can save crawl results.

## What it does

Public classes: `AsyncCrawler`, `HTMLParser`, `CrawlerQueue`, `URLFilter`,
`SemaphoreManager`.

| Piece | Role |
|---|---|
| `SemaphoreManager` | Global + per-domain in-flight request limit |
| `ClientTimeout` / `TCPConnector` | Connect/read/total timeouts and connection pool |
| `CrawlerQueue` | Pending URLs, priority, depth, seen/processed/failed |
| `URLFilter` | `same_domain_only`, include (whitelist), exclude (blacklist) |
| `fetch_url(url) -> str` | GET one page; log start/success/error type; raise HTTP/timeout/network |
| `fetch_urls(urls) -> dict[str, str]` | Parallel GET; skip those errors |
| `fetch_and_parse(url) -> dict` | Fetch + parse into the page dict |
| `crawl(start_urls, max_pages, max_depth=)` | Walk links; fill visited/processed/failed |
| `HTMLParser.parse_html(html, url)` | Same dict from raw HTML |
| `close()` / `async with` | Close the HTTP session |

Page dict: `{url, title, text, links, link_details, metadata, images, headings, tables, lists}`.

`crawl` prints live progress on stderr: processed count, queue size, errors,
pages/s.

Logging (`crawler.async_crawler`): start of a URL load, successful complete
(byte count), errors with URL and exception type (`ClientResponseError`,
`TimeoutError`, `ClientError`).

## How to start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Tiny fetch:

```bash
PYTHONPATH=. python examples/fetch_example.py
```

Crawl demo (needs network; live progress; writes `crawl_results.json`):

```bash
PYTHONPATH=. python examples/crawl_demo.py
```

Library usage:

```python
import asyncio
from crawler import AsyncCrawler

async def main():
    async with AsyncCrawler(
        max_concurrent=10,
        same_domain_only=True,
        exclude_patterns=[r"\.pdf$"],
    ) as crawler:
        results = await crawler.crawl(
            start_urls=["https://example.com"],
            max_pages=50,
            max_depth=2,
        )
        print(len(results), crawler.visited_urls, crawler.failed_urls)

asyncio.run(main())
```

Always close via `async with` or `await close()`.

## Tests

Install test extras and run (offline, fake `ClientSession`):

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```

| File | Checks |
|---|---|
| `tests/test_async_crawler.py` | fetch, timeouts, pool, logging, concurrency, session close |
| `tests/test_html_parser.py` | page dict, links, extras, parse errors |
| `tests/test_crawler_queue.py` | priority, `max_depth`, whitelist/blacklist, no duplicate enqueue |
| `tests/test_url_filter.py` | same-domain, include/exclude patterns |
| `tests/test_crawl.py` | depth cap, unique `visited_urls`, crawl-time filters |

`examples/` scripts need the network. They are not pytest tests.

`pyproject.toml` sets `asyncio_mode = auto` and `pythonpath = ["."]`.
