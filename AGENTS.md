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
  __init__.py            # exports AsyncCrawler, HTMLParser
  async_crawler.py       # AsyncCrawler (HTTP)
  html_parser.py         # HTMLParser (BeautifulSoup)
tests/                   # pytest (no network)
examples/
  fetch_example.py       # tiny usage
  parallel_demo.py       # sequential vs parallel timing
  parse_demo.py          # fetch + parse stats
requirements.txt
requirements-dev.txt
```

## Current API (step 5)

`AsyncCrawler(max_concurrent=10, *, connect_timeout=10, read_timeout=30, total_timeout=60, pool_limit=100, pool_limit_per_host=max_concurrent)`

- `fetch_url(url: str) -> str` — GET one URL, return body text
- `fetch_urls(urls: list[str]) -> dict[str, str]` — parallel GET; skip known failures
- `fetch_and_parse(url: str) -> dict` — fetch then parse (see page dict)
- `close()` — `await session.close()` then `asyncio.sleep(0)` so SSL transports finish
- also supports `async with AsyncCrawler() as c`

`HTMLParser`
- `parse_html(html, url) -> dict` — async; builds the page dict
- `extract_links(soup, base_url) -> list[str]` — relative→absolute, same-host only, validated http(s)
- `extract_link_details(soup, base_url) -> list[{href, absolute, kept, reason}]`
- `extract_text(soup, selector=None) -> str` — visible text; optional CSS selector
- `extract_metadata(soup) -> dict` — `{title, description, keywords}`
- `extract_images(soup, base_url) -> list[{src, alt}]`
- `extract_headings(soup) -> list[{level, text}]` — h1/h2/h3
- `extract_tables(soup) -> list[{headers, rows}]`
- `extract_lists(soup) -> list[{type, items}]` — ul/ol
- `to_absolute_url(href, base_url)` / `is_valid_url(url)`

Page dict: `{url, title, text, links, link_details, metadata, images, headings, tables, lists}`.
Links: relative resolved, outer hosts filtered (`www.` stripped for host compare), invalid skipped with WARNING.
Parse errors: log WARNING, return partial dict (`url` always set).

Session is created lazily in `_get_session()`:
- `ClientTimeout(total, connect, sock_read=read_timeout)` — aiohttp has no `read=`
- `TCPConnector(limit, limit_per_host, ttl_dns_cache=300, enable_cleanup_closed=True)`

Concurrency: `asyncio.Semaphore(max_concurrent)`.

Error handling (catch order — `ClientResponseError` is a `ClientError`):
- `aiohttp.ClientResponseError` — HTTP 4xx/5xx (`raise_for_status`)
- `asyncio.TimeoutError` — connect / read / total timeout
- `aiohttp.ClientError` — DNS, connection reset, etc.

`fetch_url` logs and re-raises. `fetch_urls` catches only those three and omits the URL.

## Logging

`crawler.async_crawler`:
- INFO `Fetching {url}` — start
- INFO `Fetched {url} ({n} bytes)` — success
- WARNING `HTTP error fetching {url} [{ClientResponseError}]: ...`
- WARNING `Timeout fetching {url} [TimeoutError]`
- WARNING `Network error fetching {url} [{ClientError subclass}]: ...`

`crawler.html_parser`: WARNING on invalid links, missing img src, extractor failures.

Callers configure logging (`logging.basicConfig`). Tests use `caplog`.

## Conventions

- Keep public API small and typed.
- Do not add extra deps unless asked.
- Failed URLs in `fetch_urls` are omitted, not raised.
- `fetch_url` raises the three error classes above; do not swallow them.
- Demos: `examples/parallel_demo.py`, `examples/parse_demo.py` (network). Tests stay offline.

## Do not

- Do not crawl without concurrency limits.
- Do not commit `.venv`, `__pycache__`, `.env`.

## Next likely steps

Retries, robots.txt, crawl queue from extracted links, rate limits, user-agent, persistence.