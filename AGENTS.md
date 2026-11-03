# AGENTS.md

Short context for coding agents. Read this before editing.

## Workflow

- **Before start show the plan**: what you will change and why. Do not jump into edits.
- Keep this file and README in sync with the public API.
- Prefer `async with AsyncCrawler() as c` over manual `close()`.

## What this is

Python async HTTP crawler using **aiohttp**. Package lives in `crawler/`.

## Stack

- Python 3.9+
- aiohttp 3.x
- beautifulsoup4 (stdlib `html.parser`)
- pytest + pytest-asyncio for tests

## Layout

```
crawler/                 # importable package
  __init__.py            # AsyncCrawler, HTMLParser, CrawlerQueue, URLFilter, SemaphoreManager
  async_crawler.py       # HTTP + crawl loop
  html_parser.py         # HTMLParser (BeautifulSoup)
  crawler_queue.py       # CrawlerQueue
  url_filter.py          # URLFilter
  semaphore_manager.py   # global + per-domain semaphores
tests/                   # pytest (no network)
examples/
  fetch_example.py
  parallel_demo.py
  parse_demo.py
  crawl_demo.py          # live crawl + crawl_results.json
requirements.txt
requirements-dev.txt
```

## Current API

`AsyncCrawler(max_concurrent=10, max_per_domain=2, *, connect_timeout=10, read_timeout=30, total_timeout=60, pool_limit=100, pool_limit_per_host=max_concurrent, same_domain_only=True, include_patterns=None, exclude_patterns=None)`

- `fetch_url(url: str) -> str` — GET one URL; `SemaphoreManager.limit(url)`; log start/success/error type; re-raise HTTP/timeout/network
- `fetch_urls(urls: list[str]) -> dict[str, str]` — parallel GET; skip those three error classes
- `fetch_and_parse(url: str) -> dict` — fetch then parse
- `crawl(start_urls, max_pages=100, *, max_depth=None) -> dict[str, dict]` — queue + filters + progress
- `visited_urls: set[str]`, `processed_urls: dict[str, dict]`, `failed_urls: dict[str, str]`
- `close()` — `await session.close()` then `asyncio.sleep(0)`; also `async with AsyncCrawler() as c`

Session: `ClientTimeout(total, connect, sock_read=read_timeout)` + `TCPConnector(limit, limit_per_host, ttl_dns_cache=300, enable_cleanup_closed=True)`.

`CrawlerQueue(start_urls=None, *, max_pages=None, max_depth=None, url_filter=None)`

- `add_url(url, priority=0, depth=0)` — skip seen, too deep, over max_pages, or filter reject
- `get_next() -> str | None` — highest priority first; same priority is FIFO
- `mark_processed` / `mark_failed` / `get_stats()`

`URLFilter(*, same_domain_only=True, allowed_hosts=None, include_patterns=None, exclude_patterns=None)`

- `allow(url) -> bool` — host, then include (whitelist), then exclude (blacklist). Patterns are regex.

`SemaphoreManager(max_global=10, max_per_domain=2)` — `acquire` / `release` / `limit(url)` / `get_stats()`.

`HTMLParser` — `parse_html`, `extract_links` (same-host), `extract_link_details`, text/metadata/images/headings/tables/lists.

Page dict: `{url, title, text, links, link_details, metadata, images, headings, tables, lists}`.

`crawl` builds `URLFilter` from crawler settings and seed hosts, then `CrawlerQueue`. Progress goes to stderr (`processed`, `queue`, `errors`, `pages/s`).

## Conventions

- Keep public API small and typed.
- Do not add extra deps unless asked.
- Failed URLs in `fetch_urls` are omitted, not raised.
- `fetch_url` logs and re-raises `ClientResponseError`, `TimeoutError`, `ClientError`.
- `crawl` records those errors in `failed_urls`.
- Tests stay offline (fake session in `tests/http_fakes.py`). Demos may use the network.

## Do not

- Do not crawl without concurrency limits.
- Do not commit `.venv`, `__pycache__`, `.env`, `crawl_results.json`.

## Next likely steps

Retries, robots.txt, rate limits, user-agent, persistence.
