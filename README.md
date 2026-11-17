# crawler

Async HTTP crawler on **aiohttp**. It fetches pages in parallel with a global
and per-domain concurrency cap, follows same-host links through a priority
queue, filters URLs, respects `robots.txt`, rate-limits requests, retries
temporary failures, and can save pages to JSONL, CSV, or PostgreSQL.
Optional extras (off by default): HTTP **proxy**, seed **cookies**,
**JavaScript** HTML via Playwright, and a shared **frontier** for two crawlers.

## What it does

Public classes: `AsyncCrawler`, `AdvancedCrawler`, `HTMLParser`, `CrawlerQueue`,
`URLFilter`, `SemaphoreManager`, `RateLimiter`, `RobotsParser`, `RetryStrategy`,
`CircuitBreaker`, `SitemapParser`, `CrawlerStats`, `CrawlerConfig`,
`DataStorage`, `JSONStorage`, `CSVStorage`, `PostgresStorage`.
Import `Frontier` / `InMemoryFrontier` from `crawler.frontier` and
`JsRenderer` / `PlaywrightRenderer` from `crawler.js_renderer` (not on
`from crawler import ...` yet).
`RobotsDenied` is raised when `robots.txt` forbids a URL.
`StorageError` is raised for bad save input. `normalize_page()` builds the
saved record. `load_config` / `crawler_from_config` read YAML or JSON.
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
| `fetch_url(url) -> str` | GET one page; robots + rate limit + retries; optional `proxy=`; log each try; re-raise `CrawlerError` / `RobotsDenied` |
| `fetch_urls(urls) -> dict[str, str]` | Parallel GET; skip `CrawlerError` / `RobotsDenied` |
| `fetch_and_parse(url) -> dict` | aiohttp fetch + parse, or Playwright HTML when `js_render=True`; add `status_code`, `content_type`, `crawled_at` |
| `crawl(start_urls, max_pages, max_depth=, sitemap_urls=)` | Walk links (`CrawlerQueue`); optional sitemap.xml seeds; fill visited/processed/failed; optional `storage.save_many` |
| `crawl_shared(frontier)` | Same fetch/parse/save, URLs from a shared `Frontier` (seed with `frontier.add`) |
| `proxy=` | Optional HTTP proxy URL on each GET (and robots.txt). `None` = omit the argument |
| `cookies=` | Optional seed dict for the aiohttp cookie jar (`ClientSession`) |
| `js_render` / `js_renderer` | Opt-in JS rendering; tests inject a fake; live use needs Playwright + Chromium |
| `InMemoryFrontier` | Shared seen-set + queue for two crawlers in one process (not Redis) |
| `SitemapParser` | Fetch sitemap.xml; urlset pages; follow sitemapindex |
| `CrawlerStats` / `get_crawler_stats()` | Snapshot: pages, errors, status codes, top domains; JSON/HTML/PNG export |
| `AdvancedCrawler` | Config + logs + crawl + `get_stats()` + HTML report |
| `load_config` / `crawler_from_config` | YAML/JSON → `CrawlerConfig` + `AsyncCrawler` |
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
small. `save_many` / `flush` run one at a time (`_storage_io_lock`). `save_many`
only fills the backend RAM buffer. The crawler retries **`flush()`**
(`storage_max_retries`, backoff) so a failed disk/DB write is not followed by
a second `save_many` of the same rows. Failures are logged and **do not stop**
the crawl (`storage_errors`). Backends keep their RAM buffer until `write` /
`executemany` succeeds, so a later `flush()` can still write after a failed
attempt. The crawler does **not** call `storage.close()` —
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
`result`), and `Blocked by robots.txt`. `setup_logging` (used by the CLI and
`AdvancedCrawler`) also writes a rotating `crawler.log` plus the console.

`respect_robots=True` by default. Every `fetch_url` loads `robots.txt` once
per origin and skips disallowed paths. Pass `respect_robots=False` or
`--no-respect-robots` to skip that check.

### Optional extras (defaults unchanged)

**Proxy.** `AsyncCrawler(proxy="http://127.0.0.1:8080")` passes that URL to
`session.get`. YAML: `crawler.proxy` in the config file. Omit the key (or
`proxy: null`) so requests go direct. The sample `examples/crawler.yaml` may
show a proxy line; delete it unless you actually run a local proxy.

**Cookies.** `AsyncCrawler(cookies={"sid": "abc"})` fills the session jar.
After a crawl, `_get_cookies()` returns name → value from the live jar.
This is the same `ClientSession` as keep-alive; there is no second session type.

**JavaScript.** aiohttp downloads source HTML only. `js_render=True` makes
`fetch_and_parse` (and therefore `crawl`) take HTML from a `JsRenderer`
instead of `_fetch_document`. Inject `js_renderer=` in tests. For a real
browser: `pip install -r requirements-dev.txt` then `playwright install chromium`.
`fetch_url` always stays on aiohttp.

**Shared frontier.** `crawl()` already runs several **asyncio** workers in one
process with RAM `CrawlerQueue`. `crawl_shared(frontier)` is the extra for
**two crawler objects** sharing `InMemoryFrontier` (seen URLs + pending queue).
Seed first, then gather:

```python
from crawler.frontier import InMemoryFrontier

frontier = InMemoryFrontier(max_pages=50)
await frontier.add("https://example.com")
await asyncio.gather(c1.crawl_shared(frontier), c2.crawl_shared(frontier))
```

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

Command line (`argparse`). Flags override `--config` when both are set:

```bash
PYTHONPATH=. python crawler.py --urls https://example.com --max-pages 100 --output results.json
PYTHONPATH=. python crawler.py --config examples/crawler.yaml --output results.json
PYTHONPATH=. python crawler.py --urls https://example.com --no-respect-robots --rate-limit 2
```

`--respect-robots` is on by default; `--no-respect-robots` skips `robots.txt`. `--output` is a JSON summary of the crawl (pages, failures, stats). YAML `storage:` still saves during the crawl if you pass `--config`. Put `logging:` at the **top level** of the YAML (not under `storage:`).

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

Full homework-style demo (`AdvancedCrawler.from_config`, stats, HTML report + PNG charts):

```bash
PYTHONPATH=. python examples/advanced_demo.py
```

Writes `reports/report.html` and `reports/charts/*.png`. Open the HTML in a browser (charts are also embedded). `error_report.json` is only from `error_demo.py`.

Optional local Postgres (Docker Desktop must be running; CLI may be in `~/.docker/bin`):

```bash
docker compose up -d
export DATABASE_URL=postgresql://crawler:crawler@localhost:5432/crawler
PYTHONPATH=. python examples/storage_demo.py
docker compose exec postgres psql -U crawler -d crawler -c "SELECT id, url, title FROM pages;"
```

Library usage (`AdvancedCrawler` + YAML):

```python
import asyncio
from crawler import AdvancedCrawler

async def main():
    crawler = AdvancedCrawler.from_config("examples/crawler.yaml")
    await crawler.crawl()
    stats = crawler.get_stats()
    print(f"Processed: {stats['total_pages']} pages")
    print(f"Success: {stats['successful']}")
    print(f"Errors: {stats['failed']}")
    crawler.export_to_html_report("reports/report.html")
    await crawler.close()

asyncio.run(main())
```

`get_stats()` also has `pages_processed` / `successful_requests` / `failed_requests` (same numbers as `total_pages` / `successful` / `failed`). `failed_urls` lists hosts that never became saved pages (for example `RobotsDenied` on google.com). PNG files update only if you call `export_stats(charts_dir=...)`.

Lower-level `AsyncCrawler`:

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
| `tests/test_sitemap.py` | urlset vs sitemapindex, fake session |
| `tests/test_crawler_stats.py` | summary keys, JSON/HTML export |
| `tests/test_config.py` | YAML/JSON → crawler kwargs and storage |
| `tests/test_cli.py` | argparse flags vs config |
| `tests/test_log_setup.py` | rotating file + console |
| `tests/test_progress.py` | live bar denominator |
| `tests/test_advanced_crawler.py` | `from_config`, `get_stats` aliases, `export_to_html_report` |
| `tests/test_proxy.py` | `proxy=` on GET vs omitted |
| `tests/test_cookies.py` | seed cookies on `ClientSession` |
| `tests/test_js_render.py` | fake renderer, no browser |
| `tests/test_distributed.py` | two crawlers, one `InMemoryFrontier`, no duplicate GET |
| `tests/test_performance.py` | async vs sync speed (offline fan-out) |

`examples/` scripts need the network. They are not pytest tests.

`pyproject.toml` sets `asyncio_mode = auto` and `pythonpath = ["."]`.
