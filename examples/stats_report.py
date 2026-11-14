import asyncio
from crawler import AsyncCrawler

async def main():
    async with AsyncCrawler(requests_per_second=1.0) as crawler:
        await crawler.crawl(["https://example.com"], max_pages=5, max_depth=1)
        crawler.export_to_json("reports/stats.json")
        crawler.export_to_html_report("reports/stats.html")
        crawler.stats.export_charts("reports/charts")

asyncio.run(main())