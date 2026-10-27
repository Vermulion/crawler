# crawler

Minimal async HTTP crawler on **aiohttp**.

It fetches one URL or many URLs in parallel with a shared `ClientSession`,
connect/read timeouts, connection pooling, and a concurrency cap.

## What it does

Public classes: `AsyncCrawler` (HTTP) and `HTMLParser` (BeautifulSoup).

| Piece | Role |
|---|---|
| `asyncio.Semaphore(max_concurrent)` | At most N in-flight requests |
| `aiohttp.ClientSession` | Shared session (created lazily) |
| `ClientTimeout(connect, sock_read, total)` | Stop hung connects/reads |
| `TCPConnector(limit, limit_per_host)` | Keep-alive connection pool |
| `fetch_url(url) -> str` | GET one page; raise HTTP / timeout / network errors |
| `fetch_urls(urls) -> dict[str, str]` | Parallel GET; skip those errors |
| `fetch_and_parse(url) -> dict` | Fetch + parse into `{url, title, text, links, metadata}` |
| `HTMLParser.parse_html(html, url)` | Same dict from raw HTML |
| `HTMLParser.extract_links / extract_text / extract_metadata` | Links (absolute http(s)), visible text, title/description/keywords |
| `close()` / `async with` | Close session + pool |

Logging (`crawler.async_crawler`):

- start of a URL load
- successful complete (byte count)
- errors with URL and exception type (`ClientResponseError`, `TimeoutError`, `ClientError`)

## How to start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Tiny example:

```bash
PYTHONPATH=. python examples/fetch_example.py
```

Parallel vs sequential demo (needs network; prints status + timing):

```bash
PYTHONPATH=. python examples/parallel_demo.py
```

Library usage:

```python
import asyncio
from crawler import AsyncCrawler

async def main():
    async with AsyncCrawler(max_concurrent=10) as crawler:
        html = await crawler.fetch_url("https://example.com")
        pages = await crawler.fetch_urls([
            "https://example.com",
            "https://example.org",
        ])
        print(html[:200])
        print(list(pages.keys()))

        page = await crawler.fetch_and_parse("https://example.com")
        print(page["title"], page["links"][:3])

asyncio.run(main())
```

Always close via `async with` or `await close()`.

## Tests

Install test extras and run:

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```

All tests are offline (fake `ClientSession`). Current cases in
`tests/test_async_crawler.py`:

| Test | Checks |
|---|---|
| `test_init_rejects_non_positive` | `max_concurrent >= 1` |
| `test_init_rejects_non_positive_timeouts` | timeouts and pool size |
| `test_session_uses_timeouts_and_pool` | `ClientTimeout` + `TCPConnector` + close |
| `test_fetch_url_returns_body` | success path + session close |
| `test_fetch_url_raises_http_error` | `ClientResponseError` |
| `test_fetch_url_raises_timeout` | `TimeoutError` |
| `test_fetch_url_raises_network_error` | `ClientError` |
| `test_fetch_urls_skips_http_timeout_and_network_errors` | batch skips failures |
| `test_fetch_urls_empty` | empty list |
| `test_concurrency_limit` | semaphore holds max in-flight |
| `test_context_manager_closes_session` | `async with` closes |
| `test_fetch_url_logs_start_and_success` | INFO start + success |
| `test_fetch_url_logs_error_type` | WARNING includes URL + exception class |
| `test_parse_html_returns_page_dict` | title/text/links/metadata |
| `test_extract_links_skips_non_http` | skip javascript/mailto/fragments |
| `test_extract_text_with_selector` | CSS selector + missing node |
| `test_extract_metadata_falls_back_to_og` | og:title / og:description |
| `test_fetch_and_parse_uses_parser` | crawler fetch + parse (fake session) |

`examples/parallel_demo.py` is a live network demo, not a pytest test.
