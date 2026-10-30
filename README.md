# crawler

Minimal async HTTP crawler on **aiohttp**.

It fetches one URL or many URLs in parallel with a shared `ClientSession`,
connect/read timeouts, connection pooling, and a concurrency cap.
Fetched HTML can be parsed into title, text, same-host links, images,
headings, tables, and lists.

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
| `fetch_and_parse(url) -> dict` | Fetch + parse into the page dict |
| `HTMLParser.parse_html(html, url)` | Same dict from raw HTML |
| `extract_links` | Relative → absolute, same-host only, validated http(s) |
| `extract_images / extract_headings / extract_tables / extract_lists` | Structured extras |
| `close()` / `async with` | Close session + pool |

Page dict: `{url, title, text, links, link_details, metadata, images, headings, tables, lists}`.

Parse failures log a WARNING and return a partial dict (`url` is always set).

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

Parse demo (needs network; prints stats, headings, relative vs absolute links):

```bash
PYTHONPATH=. python examples/parse_demo.py
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
        print(page["title"], page["links"][:3], len(page["images"]))

asyncio.run(main())
```

Always close via `async with` or `await close()`.

Parse demo output looks like:

```python
{
    "url": "https://example.com",
    "title": "Example Domain",
    "text_length": 1234,
    "links_count": 5,
    "links": ["https://example.com/page1", "..."],
    "images_count": 2
}
```

## Tests

Install test extras and run:

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```

All tests are offline (fake `ClientSession`). HTTP cases live in
`tests/test_async_crawler.py`; parser cases in `tests/test_html_parser.py`.

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
| `test_parse_html_returns_page_dict` | title/text/same-host links/images/headings/tables/lists |
| `test_extract_links_converts_relative_and_filters_outer` | relative → absolute, drop outer hosts |
| `test_extract_links_skips_non_http` | skip javascript/mailto/fragments |
| `test_to_absolute_url_and_validation` | resolve + `is_valid_url` |
| `test_extract_text_with_selector` | CSS selector + missing node |
| `test_extract_metadata_falls_back_to_og` | og:title / og:description |
| `test_extract_images_headings_tables_lists` | structured extras |
| `test_parse_html_handles_incorrect_html` | broken markup still returns a dict |
| `test_parse_html_returns_partial_on_extractor_error` | WARNING + empty field, rest kept |
| `test_parse_html_logs_invalid_links` | invalid href / missing img src |
| `test_www_and_bare_host_are_same_site` | `www.` does not count as outer |
| `test_extract_link_details_marks_relative_and_outer` | original href vs absolute, outer skipped |
| `test_fetch_and_parse_uses_parser` | crawler fetch + parse (fake session) |

`examples/parallel_demo.py` and `examples/parse_demo.py` are live network demos, not pytest tests.