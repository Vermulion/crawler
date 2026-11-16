"""Full AdvancedCrawler usage: config → crawl → stats → HTML report."""

from __future__ import annotations

import asyncio
from pathlib import Path

from crawler import AdvancedCrawler

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "crawler.yaml"  # or config.yaml if you rename
REPORT = ROOT.parent / "reports" / "report.html"


async def main() -> None:
    crawler = AdvancedCrawler.from_config(CONFIG)

    await crawler.crawl()

    stats = crawler.get_stats()
    print(f"Processed: {stats['total_pages']} pages")
    print(f"Success: {stats['successful']}")
    print(f"Errors: {stats['failed']}")
    print("Failed URLs:", stats.get("failed_urls") or {})

    crawler.export_to_html_report(str(REPORT))
    crawler.export_stats(charts_dir=str(ROOT.parent / "reports" / "charts"))
    print(f"Report exported to {REPORT}")
    print(f"Charts exported to {ROOT.parent / 'reports' / 'charts'}")
    await crawler.close()


if __name__ == "__main__":
    asyncio.run(main())