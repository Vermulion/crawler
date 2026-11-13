# crawler

Async HTTP crawler on **aiohttp**. It fetches pages in parallel with a global
and per-domain concurrency cap, follows same-host links through a priority
queue, filters URLs, respects `robots.txt`, rate-limits requests, retries
temporary failures, and can save pages to JSONL, CSV, or PostgreSQL.

## What it does

Public classes: `AsyncCrawler`, `HTMLParser`, `CrawlerQueue`, `URLFilter`,
`SemaphoreManager`, `RateLimiter`, `RobotsParser`, `RetryStrategy`,
`CircuitBreaker`, `DataStorage`, `JSONStorage`, `CSVStorage`,
`PostgresStorage`. `RobotsDenied` is raised when `robots.txt` forbids a URL.
`StorageError` is raised for bad save input. `normalize_page()` builds the
saved record.
Load failures are mapped to `CrawlerError` subclasses (`TransientError`,
`PermanentError`, `NetworkError`, `ParseError`, `CircuitOpenError`).

| Piece | Role |
|---|---|
| `SemaphoreManager` | Global + per-domain in-flight request limit |
| `RateLimiter` | Gap between request starts (`requests_per_second`, `min_delay`, jitter) |
| `RobotsParser` | Cache `robots.txt`; `can_fetch` / `Crawl-delay` per user-agent |
| `RetryStrategy` | Extra tries after temporary errors; exponential backoff; 429 waits longer; 500 has a smaller retry cap |
| `CircuitBreaker` | Block a domain after many recent failures; reopen after `recovery_timeout` |
| `ClientTimeout` / `TCPConnector` | Connect/read/total timeouts; retries can grow timeouts up to `timeout_max` |
| `CrawlerQueue` | Pending URLs, priority, depth, seen/processed/failed |
| `URLFilter` | `same_domain_only`, include (whitelist), exclude (blacklist) |
| `fetch_url(url) -> str` | GET one page; robots + rate limit + retries; log each try; re-raise `CrawlerError` / `RobotsDenied` |
| `fetch_urls(urls) -> dict[str, str]` | Parallel GET; skip `CrawlerError` / `RobotsDenied` |
| `fetch_and_parse(url) -> dict` | Fetch + parse; add `status_code`, `content_type`, `crawled_at` |
| `crawl(start_urls, max_pages, max_depth=)` | Walk links; fill visited/processed/failed; optional `storage.save_many` |
| `JSONStorage` / `CSVStorage` / `PostgresStorage` | Async `save` / `save_many` / `flush` / `close`; JSONL, CSV, or PostgreSQL |
| `normalize_page(data)` | Standard saved fields (drops parser extras such as `images`) |
| `error_log` | Per-try rows: `error`, `url`, `attempt`, `retry_in`, `result` (`retry` / `failure` / `success`) |
| `get_error_stats()` | Counts by type, successful retries, average retry wait, URLs with permanent errors |
| `get_speed_stats()` | `requests_per_second`, `avg_delay`, `blocked`, `requests` |
| `HTMLParser.parse_html(html, url)` | Same dict from raw HTML |
| `close()` / `async with` | `storage.flush()` (does not close storage), then close the HTTP session |

Parser page dict: `{url, title, text, links, link_details, metadata, images, headings, tables, lists}`.
Saved record: `{url, title, text, links, metadata, crawled_at, status_code, content_type}`.

Pass `storage=` into `AsyncCrawler`. After each successful page, the crawler
buffers rows and calls `save_many` every `storage_batch_size` pages (and at
the end of `crawl` / `close`). Then it calls `storage.flush()` so RAM buffers
(`JSONStorage` / `CSVStorage` `_chunks`) reach the file even when the crawl is
small. `save_many` / `flush` run one at a time (`_storage_io_lock`). Disk or DB
errors (`save_many` and `flush`) are retried (`storage_max_retries`, backoff);
they are logged and **do not stop** the crawl (`storage_errors`). Backends keep
their RAM buffer until `write` / `executemany` succeeds, so a later `flush()`
can still write after a failed attempt. The crawler does **not** call `storage.close()` —
close the storage yourself (`async with JSONStorage(...)`) when you are done
with the file or DB. `PostgresStorage` needs a DSN
`postgresql://user:pass@host:5432/dbname`, not a `.db` file.

`crawl` prints live progress on stderr: processed count, queue size, errors,
pages/s, req/s, average delay, robots blocked.

### HTTP status and retries

| Status | Class | Retry? |
|---|---|---|
| 401, 403, 404 | `PermanentError` | no |
| 429 | `TransientError` | yes, longer delay (`retry_429_factor`) |
| 500 | `TransientError` | yes, at most `max_retries_500` extra tries (default 1) |
| 503 | `TransientError` | yes, up to `max_retries` |
| timeout / connection | `NetworkError` (a `TransientError`) | yes |

Backoff wait after failure *n* (0-based): `backoff_factor * 2**n`, capped by
`backoff_max`. `asyncio.TimeoutError` becomes `NetworkError`.

Logging (`crawler.async_crawler`): start of a URL load (try number and timeout),
success (byte count), each error row (`url`, `error`, `attempt`, `retry_in`,
`result`), and `Blocked by robots.txt`.

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

Error-handling demo (404/403/5xx/429/timeout, retries, stats; writes `error_report.json`):

```bash
PYTHONPATH=. python examples/error_demo.py
```

Storage demo (network; writes `results.jsonl` and `results.csv`; Postgres if `DATABASE_URL` is set):

```bash
PYTHONPATH=. python examples/storage_demo.py
```

Optional local Postgres (Docker Desktop must be running; CLI may be in `~/.docker/bin`):

```bash
docker compose up -d
export DATABASE_URL=postgresql://crawler:crawler@localhost:5432/crawler
PYTHONPATH=. python examples/storage_demo.py
docker compose exec postgres psql -U crawler -d crawler -c "SELECT id, url, title FROM pages;"
```

Library usage:

```python
import asyncio
from crawler import AsyncCrawler, JSONStorage
from crawler.errors import CrawlerError

async def main():
    async with JSONStorage("pages.jsonl", indent=None) as storage:
        async with AsyncCrawler(
            max_concurrent=5,
            requests_per_second=2.0,
            min_delay=0.5,
            max_retries=2,
            backoff_factor=0.5,
            user_agent="MyBot/1.0",
            same_domain_only=True,
            exclude_patterns=[r"\.pdf$"],
            storage=storage,
            storage_batch_size=10,
        ) as crawler:
            results = await crawler.crawl(
                start_urls=["https://example.com"],
                max_pages=50,
                max_depth=2,
            )
            print(len(results), crawler.visited_urls, crawler.failed_urls)
            print(crawler.get_speed_stats())
            print(crawler.get_error_stats())
            print(crawler.storage_errors)

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
| `tests/test_crawl.py` | depth cap, unique `visited_urls`, crawl-time filters, storage batch/retry, JSON record from crawl |
| `tests/test_storage.py` | JSON/CSV/Postgres save, buffers, `normalize_page`, record integrity, fake DB |
| `tests/test_rate_limiter.py` | one domain, several domains, global clock, `min_delay` |
| `tests/test_robots_parser.py` | parse, user-agent groups, crawl-delay, 404/403 |
| `tests/test_politeness.py` | forbidden URL, crawl records the block, delay and rate limits |
| `tests/test_errors.py` | error class tree, HTTP classify, timeout → `NetworkError` |
| `tests/test_retry_strategy.py` | `execute_with_retry`, exponential backoff, 404 vs 503 |
| `tests/test_crawler_retry.py` | timeout retries, 503/500/429, 404 no retry, growing timeouts, `error_log`, `get_error_stats()` |
| `tests/test_circuit_breaker.py` | open / half-open / recover; crawler skips an open domain |

`examples/` scripts need the network. They are not pytest tests.

`pyproject.toml` sets `asyncio_mode = auto` and `pythonpath = ["."]`.
