# crawler

Async HTTP crawler on **aiohttp**. It fetches pages in parallel with a global
and per-domain concurrency cap, follows same-host links through a priority
queue, filters URLs, respects `robots.txt`, rate-limits requests, and can
save crawl results.

## What it does

Public classes: `AsyncCrawler`, `HTMLParser`, `CrawlerQueue`, `URLFilter`,
`SemaphoreManager`, `RateLimiter`, `RobotsParser`. `RobotsDenied` is raised
when `robots.txt` forbids a URL.

| Piece | Role |
|---|---|
| `SemaphoreManager` | Global + per-domain in-flight request limit |
| `RateLimiter` | Gap between request starts (`requests_per_second`, `min_delay`, jitter) |
| `RobotsParser` | Cache `robots.txt`; `can_fetch` / `Crawl-delay` per user-agent |
| `ClientTimeout` / `TCPConnector` | Connect/read/total timeouts and connection pool |
| `CrawlerQueue` | Pending URLs, priority, depth, seen/processed/failed |
| `URLFilter` | `same_domain_only`, include (whitelist), exclude (blacklist) |
| `fetch_url(url) -> str` | GET one page; robots + rate limit; log start/success/error type |
| `fetch_urls(urls) -> dict[str, str]` | Parallel GET; skip HTTP/timeout/network/`RobotsDenied` |
| `fetch_and_parse(url) -> dict` | Fetch + parse into the page dict |
| `crawl(start_urls, max_pages, max_depth=)` | Walk links; fill visited/processed/failed |
| `get_speed_stats()` | `requests_per_second`, `avg_delay`, `blocked`, `requests` |
| `HTMLParser.parse_html(html, url)` | Same dict from raw HTML |
| `close()` / `async with` | Close the HTTP session |

Page dict: `{url, title, text, links, link_details, metadata, images, headings, tables, lists}`.

`crawl` prints live progress on stderr: processed count, queue size, errors,
pages/s, req/s, average delay, robots blocked.

Logging (`crawler.async_crawler`): start of a URL load, successful complete
(byte count), errors with URL and exception type (`ClientResponseError`,
`TimeoutError`, `ClientError`), and `Blocked by robots.txt`.

There is no `respect_robots` flag. Every `fetch_url` loads `robots.txt` once
per origin and skips disallowed paths.

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

Politeness demo (rate limit, `robots.txt`, delay stats, a forbidden URL):

```bash
PYTHONPATH=. python examples/polite_demo.py
```

Library usage:

```python
import asyncio
from crawler import AsyncCrawler

async def main():
    async with AsyncCrawler(
        max_concurrent=5,
        requests_per_second=2.0,
        min_delay=0.5,
        user_agent="MyBot/1.0",
        same_domain_only=True,
        exclude_patterns=[r"\.pdf$"],
    ) as crawler:
        results = await crawler.crawl(
            start_urls=["https://example.com"],
            max_pages=50,
            max_depth=2,
        )
        print(len(results), crawler.visited_urls, crawler.failed_urls)
        print(crawler.get_speed_stats())

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
| `tests/test_rate_limiter.py` | one domain, several domains, global clock, `min_delay` |
| `tests/test_robots_parser.py` | parse, user-agent groups, crawl-delay, 404/403 |
| `tests/test_politeness.py` | forbidden URL, crawl records the block, delay and rate limits |

`examples/` scripts need the network. They are not pytest tests.

`pyproject.toml` sets `asyncio_mode = auto` and `pythonpath = ["."]`.
