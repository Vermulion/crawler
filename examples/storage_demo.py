"""Live demo: crawl, save to JSON + CSV (and Postgres if DATABASE_URL is set)."""

from __future__ import annotations

import asyncio
import csv
import json
import os
from pathlib import Path

from crawler import AsyncCrawler, CSVStorage, DataStorage, JSONStorage, PostgresStorage

START_URLS = ["https://example.com"]
JSON_PATH = Path("results.jsonl")
CSV_PATH = Path("results.csv")


class FanoutStorage(DataStorage):
    """Send the same pages to several backends (JSON, CSV, Postgres)."""

    def __init__(self, backends: list[DataStorage]) -> None:
        self.backends = backends

    async def save(self, data: dict) -> None:
        await self.save_many([data])

    async def save_many(self, rows: list[dict]) -> None:
        for backend in self.backends:
            await backend.save_many(rows)

    async def close(self) -> None:
        for backend in self.backends:
            await backend.close()

    async def flush(self) -> None:
        for backend in self.backends:
            await backend.flush()


def _print_json_sample(path: Path) -> None:
    if not path.exists() or path.stat().st_size == 0:
        print("JSON file is empty")
        return
    first = path.read_text(encoding="utf-8").strip().splitlines()[0]
    rec = json.loads(first)
    print("First JSONL record")
    print(f"  url:          {rec.get('url')}")
    print(f"  title:        {rec.get('title')}")
    print(f"  status_code:  {rec.get('status_code')}")
    print(f"  content_type: {rec.get('content_type')}")
    print(f"  crawled_at:   {rec.get('crawled_at')}")
    text = rec.get("text") or ""
    print(f"  text[:80]:    {text[:80]!r}")


def _print_file_stats() -> None:
    json_lines = 0
    if JSON_PATH.exists():
        json_lines = len(JSON_PATH.read_text(encoding="utf-8").strip().splitlines())
        json_bytes = JSON_PATH.stat().st_size
    else:
        json_bytes = 0
    csv_rows = 0
    if CSV_PATH.exists():
        with CSV_PATH.open(encoding="utf-8", newline="") as fh:
            csv_rows = max(0, sum(1 for _ in csv.DictReader(fh)))
    print("Saved files")
    print(f"  {JSON_PATH.resolve()}  lines={json_lines}  bytes={json_bytes}")
    print(f"  {CSV_PATH.resolve()}   data rows={csv_rows}")


async def main() -> None:
    dsn = os.environ.get("DATABASE_URL", "").strip()
    backends: list[DataStorage] = [
        JSONStorage(JSON_PATH, indent=None),
        CSVStorage(CSV_PATH),
    ]
    if dsn:
        pg = PostgresStorage(dsn, batch_size=50)
        await pg.init_db()
        backends.append(pg)
        print(f"Postgres: {dsn}")
    else:
        print("Postgres skipped (set DATABASE_URL=postgresql://user:pass@localhost:5432/crawler)")

    fanout = FanoutStorage(backends)
    async with AsyncCrawler(
        storage=fanout,
        storage_batch_size=10,
        max_concurrent=5,
        same_domain_only=True,
        requests_per_second=2.0,
        user_agent="AsyncCrawler-storage-demo",
    ) as crawler:
        results = await crawler.crawl(
            start_urls=START_URLS,
            max_pages=15,
            max_depth=1,
        )
        print("\nCrawl statistics")
        print(f"  processed:       {len(results)}")
        print(f"  failed HTTP:     {len(crawler.failed_urls)}")
        print(f"  storage errors:  {len(crawler.storage_errors)}")
        print(f"  speed:           {crawler.get_speed_stats()}")
        if crawler.storage_errors:
            print(f"  storage_errors:  {crawler.storage_errors}")

    await fanout.close()
    print()
    _print_file_stats()
    print()
    _print_json_sample(JSON_PATH)


if __name__ == "__main__":
    asyncio.run(main())