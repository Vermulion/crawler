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
- aiofiles (JSON/CSV), asyncpg (PostgreSQL)
- pytest + pytest-asyncio for tests

## Layout

```
crawler/                 # importable package
  __init__.py            # AsyncCrawler, HTMLParser, CrawlerQueue, URLFilter,
                         # SemaphoreManager, RateLimiter, RobotsParser, RobotsDenied,
                         # RetryStrategy, CircuitBreaker, CrawlerError types,
                         # DataStorage, JSONStorage, CSVStorage, PostgresStorage
  async_crawler.py       # HTTP + crawl loop + error_log / get_error_stats + storage flush
  html_parser.py         # HTMLParser (BeautifulSoup)
  crawler_queue.py       # CrawlerQueue
  url_filter.py          # URLFilter
  semaphore_manager.py   # global + per-domain semaphores
  rate_limiter.py        # requests_per_second, min_delay, jitter
  robots_parser.py       # robots.txt cache, can_fetch, crawl-delay
  retry_strategy.py      # exponential backoff, status-specific retries
  circuit_breaker.py     # per-domain open / half-open / closed
  errors.py              # CrawlerError tree + classify_status / classify_exception
  storage.py             # DataStorage ABC; JSON / CSV / Postgres; normalize_page
tests/                   # pytest (no network)
examples/
  fetch_example.py
  parallel_demo.py
  parse_demo.py
  crawl_demo.py          # live crawl + crawl_results.json
  polite_demo.py         # rate limit + robots.txt + delay stats
  error_demo.py          # mixed HTTP errors + retries + error_report.json
  storage_demo.py        # crawl → JSONL + CSV; Postgres if DATABASE_URL
docker-compose.yml       # optional local Postgres for the storage demo
requirements.txt
requirements-dev.txt
```

## Current API

`AsyncCrawler(max_concurrent=10, max_per_domain=2, *, connect_timeout=10, read_timeout=30, total_timeout=60, timeout_backoff_factor=2, timeout_max=120, pool_limit=100, pool_limit_per_host=max_concurrent, same_domain_only=True, include_patterns=None, exclude_patterns=None, requests_per_second=1.0, rate_limit_per_domain=True, min_delay=0, jitter=0, max_retries=0, backoff_factor=0.5, backoff_max=30, retry_strategy=None, circuit_breaker=None, failure_threshold=5, failure_window=60, recovery_timeout=30, user_agent="AsyncCrawler", user_agents=None, storage=None, storage_batch_size=1, storage_max_retries=2, storage_backoff_factor=0.5)`

- `fetch_url(url: str) -> str` — GET one URL; robots.txt; circuit breaker; rate limiter; `SemaphoreManager.limit(url)`; per-try timeout; `RetryStrategy`; `_record` into `error_log`; re-raise `CrawlerError` / `RobotsDenied`
- `fetch_urls(urls: list[str]) -> dict[str, str]` — parallel GET; skip `CrawlerError` / `RobotsDenied`
- `fetch_and_parse(url: str) -> dict` — fetch then parse; sets `status_code`, `content_type`, `crawled_at`
- `crawl(start_urls, max_pages=100, *, max_depth=None) -> dict[str, dict]` — queue + filters + progress; clears `error_log` and rebuilds the circuit breaker; if `storage` is set, `save_many` in batches then `storage.flush()`
- `visited_urls: set[str]`, `processed_urls: dict[str, dict]`, `failed_urls: dict[str, str]`, `blocked_urls: set[str]`, `error_log: list[dict]`, `storage_errors: list[dict]`
- `get_speed_stats() -> dict` — `requests_per_second`, `avg_delay`, `blocked`, `requests`
- `get_error_stats() -> dict` — `by_type`, `successful_retries`, `avg_retry_time`, `permanent_error_urls`
- `close()` — leftover crawler rows, then `storage.flush()` (does **not** close `storage`), then `await session.close()`; also `async with AsyncCrawler() as c`

Storage I/O is serialized: `_storage_lock` guards `_storage_buffer`; `_storage_io_lock` guards `save_many` / `flush` so workers do not hit the same backend together (CSV header, asyncpg “another operation is in progress”).

Storage save failures: retry `storage_max_retries` extra times, log WARNING/ERROR, continue the crawl. HTTP `RetryStrategy` is not used for disk/DB errors. `flush()` failures are logged the same way and do not stop the crawl.

Saved record (`normalize_page` / `RECORD_FIELDS`): `{url, title, text, links, metadata, crawled_at, status_code, content_type}`. Parser extras (`images`, …) are dropped on save. `crawled_at` is ISO-8601 in JSON/CSV.

`JSONStorage(path, indent=2, buffer_bytes=65536)` — JSONL; encode in a thread; RAM buffer until `buffer_bytes` or `flush()` / `close()`. Use `indent=None` for compact lines.

`CSVStorage(path, encoding="utf-8", buffer_bytes=65536)` — auto header; quoting; same buffer pattern.

`PostgresStorage(dsn, table="pages", batch_size=100, connect=None)` — `init_db()` table + indexes; `executemany`; tests inject `connect=`. DSN is `postgresql://…`, not a `.db` file. `flush()` sends the row buffer.

`DataStorage` — ABC: `save`, `save_many`, `flush`, `close`. Default `flush()` is a no-op. JSON/CSV `flush()` writes `_chunks` without closing the file. Crawler `crawl` / `close` call `flush()` so a small crawl still hits disk. Prefer `async with` on the storage object when you are done with the file/DB.

Session: `ClientTimeout(total, connect, sock_read=read_timeout)` + `TCPConnector(limit, limit_per_host, ttl_dns_cache=300, enable_cleanup_closed=True)`. Each GET may pass a larger timeout: `base * timeout_backoff_factor**attempt`, capped by `timeout_max`.

`CrawlerQueue(start_urls=None, *, max_pages=None, max_depth=None, url_filter=None)`

- `add_url(url, priority=0, depth=0)` — skip seen, too deep, over max_pages, or filter reject
- `get_next() -> str | None` — highest priority first; same priority is FIFO
- `mark_processed` / `mark_failed` / `get_stats()`

`URLFilter(*, same_domain_only=True, allowed_hosts=None, include_patterns=None, exclude_patterns=None)`

- `allow(url) -> bool` — host, then include (whitelist), then exclude (blacklist). Patterns are regex.

`SemaphoreManager(max_global=10, max_per_domain=2)` — `acquire` / `release` / `limit(url)` / `get_stats()`.

`RateLimiter(requests_per_second=1.0, per_domain=True, min_delay=0, jitter=0)` — `acquire(domain, min_interval=0)`.

`RetryStrategy(max_retries=3, backoff_factor=2.0, retry_on=None, backoff_max=30, max_retries_500=1, retry_429_factor=2.0)` — `execute_with_retry(fn, *args, **kwargs)`. Default `retry_on` is `TransientError`. Delay is `backoff_factor * 2**attempt`. 404/403/401 are not retried; 429/500/503 are. Crawler default `max_retries` is **0**.

`CircuitBreaker(failure_threshold=5, failure_window=60, recovery_timeout=30)` — `allow` / `record_success` / `record_failure` per domain. Only `TransientError` from `fetch_url` calls `record_failure`.

`RobotsParser` — `fetch_robots` / `store` / `can_fetch` / `get_crawl_delay`. `RobotsDenied` is raised when a URL is disallowed.

`HTMLParser` — `parse_html`, `extract_links` (same-host), `extract_link_details`, text/metadata/images/headings/tables/lists.

Parser page dict: `{url, title, text, links, link_details, metadata, images, headings, tables, lists}` plus crawl fields `status_code`, `content_type`, `crawled_at`.

`crawl` builds `URLFilter` from crawler settings and seed hosts, then `CrawlerQueue`. Progress goes to stderr (`processed`, `queue`, `errors`, `pages/s`, `req/s`, `avg_delay`, `robots_blocked`).

`error_log` row: `{url, error, attempt, retry, retry_in, result, status, message}`. `result` is `retry`, `failure`, or `success`.

## Conventions

- Keep public API small and typed.
- Do not add extra deps unless asked.
- Failed URLs in `fetch_urls` are omitted, not raised.
- `fetch_url` logs and re-raises `CrawlerError` (`TransientError` / `PermanentError` / `NetworkError` / `CircuitOpenError`) and `RobotsDenied`. aiohttp errors are classified first.
- `crawl` records those errors in `failed_urls`.
- Tests stay offline (fake session in `tests/http_fakes.py`). Demos may use the network.

## Do not

- Do not crawl without concurrency limits.
- Do not commit `.venv`, `__pycache__`, `.env`, `crawl_results.json`, `error_report.json`, `results.jsonl`, `results.csv`.

## Next likely steps

robots.txt refresh, configurable respect_robots flag.
