from pathlib import Path

import pytest

from crawler.advanced_crawler import AdvancedCrawler
from crawler.storage import JSONStorage
from tests.test_crawl import _crawl_with_pages, _page


def test_from_config_wires_storage_and_limits(tmp_path: Path) -> None:
    cfg = tmp_path / "c.yaml"
    cfg.write_text(
        "crawler:\n  max_concurrent: 3\n"
        "start_urls:\n  - https://a.test/\n"
        "crawl:\n  max_pages: 7\n  max_depth: 1\n"
        "storage:\n  type: json\n  path: out.jsonl\n",
        encoding="utf-8",
    )
    bot = AdvancedCrawler.from_config(cfg, setup_logs=False)
    assert bot.crawler.max_concurrent == 3
    assert bot.cfg.max_pages == 7
    assert bot.cfg.start_urls == ["https://a.test/"]
    assert isinstance(bot.crawler.storage, JSONStorage)


@pytest.mark.asyncio
async def test_advanced_crawl_and_stats(tmp_path: Path) -> None:
    mapping = {"https://site.test/": _page("https://site.test/")}
    inner, _session = await _crawl_with_pages(
        mapping, ["https://site.test/"], max_depth=0
    )
    # reuse pattern: build Advanced around a crawler that already crawled
    from crawler.config import CrawlerConfig

    bot = AdvancedCrawler(inner, CrawlerConfig(crawler_kwargs={}), setup_logs=False)
    stats = bot.get_stats()
    assert stats["pages_processed"] == 1
    json_path = tmp_path / "s.json"
    bot.export_stats(json_path=str(json_path))
    assert json_path.exists()
    assert stats["total_pages"] == stats["pages_processed"]
    assert stats["successful"] == stats["successful_requests"]
    assert stats["failed"] == stats["failed_requests"]
    html_path = tmp_path / "report.html"
    bot.export_to_html_report(str(html_path))
    assert html_path.exists()
    await bot.close()