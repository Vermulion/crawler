"""Live demo: mixed HTTP errors, retries, stats, save error_report.json."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from crawler import AsyncCrawler
from crawler.errors import CrawlerError

OUT_PATH = Path("error_report.json")

# Labels are for the console only. URLs are real public test endpoints.
CASES = [
    ("200 ok", "https://example.com"),
    ("404 permanent", "https://httpbin.org/status/404"),
    ("403 permanent", "https://httpbin.org/status/403"),
    ("500 retry then fail", "https://httpbin.org/status/500"),
    ("503 retry then fail", "https://httpbin.org/status/503"),
    ("429 retry, longer wait", "https://httpbin.org/status/429"),
    ("timeout (slow body)", "https://httpbin.org/delay/10"),
]


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    async with AsyncCrawler(
        max_concurrent=2,
        requests_per_second=1.0,
        min_delay=0.3,
        jitter=0.0,
        max_retries=2,
        backoff_factor=0.5,
        backoff_max=8.0,
        connect_timeout=5.0,
        read_timeout=5.0,
        total_timeout=2.0,  # delay/10 will time out
        timeout_backoff_factor=2.0,
        timeout_max=8.0,
        user_agent="AsyncCrawler-error-demo",
        failure_threshold=20,  # do not trip the breaker during the demo
    ) as crawler:
        print("Fetching URLs (watch INFO logs for try 1/3, 2/3, ...)\n")
        for label, url in CASES:
            print(f"--- {label}")
            print(f"    {url}")
            try:
                body = await crawler.fetch_url(url)
                print(f"    OK, {len(body)} bytes")
            except CrawlerError as exc:
                print(f"    {type(exc).__name__}: {exc}")
            print()

        stats = crawler.get_error_stats()
        print("Error statistics")
        print(f"  by type:                 {stats['by_type']}")
        print(f"  successful retries:      {stats['successful_retries']}")
        print(f"  avg retry wait (s):      {stats['avg_retry_time']:.2f}")
        print(f"  URLs with permanent errors: {stats['permanent_error_urls']}")
        print(f"  failed_urls:             {len(crawler.failed_urls)}")

        report = {
            "error_stats": stats,
            "failed_urls": crawler.failed_urls,
            "error_log": crawler.error_log,
        }

    OUT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nSaved error report: {OUT_PATH.resolve()}")


if __name__ == "__main__":
    asyncio.run(main())