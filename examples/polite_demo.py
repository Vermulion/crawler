"""Live demo: robots.txt, rate limits, delay stats, blocked URL."""

from __future__ import annotations

import asyncio
import logging

from crawler import AsyncCrawler
from crawler.robots_parser import RobotsDenied

START_URL = "https://crawler-test.com/"
FORBIDDEN_URL = "https://crawler-test.com/disallowed"


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    async with AsyncCrawler(
        max_concurrent=5,
        requests_per_second=2.0,
        min_delay=0.5,
        user_agent="MyBot/1.0",
        same_domain_only=True,
    ) as crawler:
        results = await crawler.crawl(
            start_urls=[START_URL],
            max_pages=8,
            max_depth=1,
        )
        stats = crawler.get_speed_stats()
        print()
        print(f"Processed: {len(results)} pages")
        print(f"Failed: {len(crawler.failed_urls)}")
        print(
            "Delay stats: "
            f"req/s={stats['requests_per_second']:.2f}  "
            f"avg_delay={stats['avg_delay']:.2f}s  "
            f"requests={stats['requests']}  "
            f"robots_blocked={stats['blocked']}"
        )

        print()
        print(f"Trying forbidden URL: {FORBIDDEN_URL}")
        try:
            await crawler.fetch_url(FORBIDDEN_URL)
            print("Unexpected: the forbidden URL was downloaded")
        except RobotsDenied:
            print("Blocked by robots.txt, as expected")
        print(f"blocked_urls: {sorted(crawler.blocked_urls)}")
        print(f"robots_blocked after demo: {crawler.get_speed_stats()['blocked']}")


if __name__ == "__main__":
    asyncio.run(main())