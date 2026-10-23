"""Demo: fetch several URLs sequentially vs in parallel.

Shows per-request status, wall-clock time, and why concurrent IO wins.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Optional

import aiohttp

from crawler import AsyncCrawler

URLS = [
    "https://example.com",
    "https://example.org",
    "https://www.python.org",
    "https://httpbin.org/get",
    "https://httpbin.org/html",
    "https://httpbin.org/delay/1",
    "https://httpbin.org/status/404",
    "https://jsonplaceholder.typicode.com/todos/1",
]


@dataclass
class RequestStatus:
    url: str
    ok: bool
    bytes: int = 0
    elapsed_s: float = 0.0
    error_type: Optional[str] = None
    error: Optional[str] = None


async def fetch_one(crawler: AsyncCrawler, url: str) -> RequestStatus:
    started = time.perf_counter()
    try:
        body = await crawler.fetch_url(url)
        return RequestStatus(
            url=url,
            ok=True,
            bytes=len(body),
            elapsed_s=time.perf_counter() - started,
        )
    except (aiohttp.ClientResponseError, asyncio.TimeoutError, aiohttp.ClientError) as exc:
        return RequestStatus(
            url=url,
            ok=False,
            elapsed_s=time.perf_counter() - started,
            error_type=type(exc).__name__,
            error=str(exc),
        )


def print_statuses(title: str, results: list[RequestStatus], wall_s: float) -> None:
    print(f"\n=== {title} ({wall_s:.2f}s wall) ===")
    for item in results:
        if item.ok:
            print(f"OK   {item.elapsed_s:5.2f}s  {item.bytes:7d} B  {item.url}")
        else:
            print(f"FAIL {item.elapsed_s:5.2f}s  {item.error_type:<24} {item.url}")
    ok = sum(1 for item in results if item.ok)
    print(f"summary: {ok}/{len(results)} ok")


async def run_sequential(urls: list[str]) -> tuple[list[RequestStatus], float]:
    async with AsyncCrawler(max_concurrent=1) as crawler:
        started = time.perf_counter()
        results = [await fetch_one(crawler, url) for url in urls]
        return results, time.perf_counter() - started


async def run_parallel(urls: list[str], max_concurrent: int) -> tuple[list[RequestStatus], float]:
    async with AsyncCrawler(max_concurrent=max_concurrent) as crawler:
        started = time.perf_counter()
        results = list(await asyncio.gather(*(fetch_one(crawler, url) for url in urls)))
        return results, time.perf_counter() - started


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    max_concurrent = min(10, len(URLS))

    sequential, sequential_s = await run_sequential(URLS)
    print_statuses("sequential (max_concurrent=1)", sequential, sequential_s)

    parallel, parallel_s = await run_parallel(URLS, max_concurrent=max_concurrent)
    print_statuses(f"parallel (max_concurrent={max_concurrent})", parallel, parallel_s)

    speedup = sequential_s / parallel_s if parallel_s else float("inf")
    print("\n=== comparison ===")
    print(f"sequential: {sequential_s:.2f}s")
    print(f"parallel:   {parallel_s:.2f}s")
    print(f"speedup:    {speedup:.2f}x")
    print(
        "HTTP waits on the network. Sequential pays for every wait in a line; "
        "parallel overlaps those waits, so wall time is closer to the slowest "
        "request than to the sum of all requests."
    )


if __name__ == "__main__":
    asyncio.run(main())
