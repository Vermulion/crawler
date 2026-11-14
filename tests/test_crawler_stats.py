from __future__ import annotations

import pytest

import json
from pathlib import Path
from crawler.crawler_stats import CrawlerStats
from tests.http_fakes import FakeResponse, FakeSession, http_error
from tests.test_crawl import _crawl_with_pages, _page


@pytest.mark.asyncio
async def test_stats_after_successful_crawl() -> None:
    mapping = {
        "https://site.test/": _page("https://site.test/", "https://site.test/b"),
        "https://site.test/b": _page("https://site.test/b"),
    }
    crawler, _session = await _crawl_with_pages(
        mapping, ["https://site.test/"], max_depth=1
    )
    stats = crawler.get_crawler_stats()
    assert stats["pages_processed"] == 2
    assert stats["successful_requests"] == 2
    assert stats["failed_requests"] == 0
    assert stats["status_codes"][200] == 2
    assert stats["top_domains"][0] == ("site.test", 2)
    assert stats["elapsed_seconds"] >= 0
    assert stats["avg_pages_per_second"] >= 0
    await crawler.close()


@pytest.mark.asyncio
async def test_stats_counts_failed_status() -> None:
    mapping = {
        "https://ok.test/": _page("https://ok.test/"),
        "https://bad.test/missing": FakeResponse(
            "nope", status=404, url="https://bad.test/missing"
        ),
    }
    crawler, _session = await _crawl_with_pages(
        mapping,
        ["https://ok.test/", "https://bad.test/missing"],
        max_depth=0,
        same_domain_only=False,
    )
    stats = crawler.get_crawler_stats()
    assert stats["pages_processed"] == 1
    assert stats["failed_requests"] == 1
    assert stats["status_codes"][200] == 1
    assert stats["status_codes"][404] == 1
    hosts = dict(stats["top_domains"])
    assert hosts["ok.test"] == 1
    await crawler.close()


def test_stats_empty_crawler() -> None:
    from crawler import AsyncCrawler

    crawler = AsyncCrawler(requests_per_second=1000.0, min_delay=0.0, jitter=0.0)
    stats = CrawlerStats(crawler).summary()
    assert stats["pages_processed"] == 0
    assert stats["failed_requests"] == 0
    assert stats["status_codes"] == {}
    assert stats["top_domains"] == []

@pytest.mark.asyncio
async def test_export_json_and_html(tmp_path: Path) -> None:
    mapping = {
        "https://site.test/": _page("https://site.test/", "https://site.test/b"),
        "https://site.test/b": _page("https://site.test/b"),
    }
    crawler, _session = await _crawl_with_pages(
        mapping, ["https://site.test/"], max_depth=1
    )
    json_path = tmp_path / "stats.json"
    html_path = tmp_path / "stats.html"
    charts_dir = tmp_path / "charts"
    crawler.stats.export_to_json(str(json_path))
    crawler.stats.export_to_html_report(str(html_path))
    saved = crawler.stats.export_charts(str(charts_dir))
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["pages_processed"] == 2
    assert data["top_domains"][0][0] == "site.test"
    html = html_path.read_text(encoding="utf-8")
    assert "<table>" in html
    assert "data:image/png;base64," in html
    assert "site.test" in html
    assert set(saved) == {"status_codes", "top_domains", "success_fail"}
    for path in saved.values():
        assert Path(path).stat().st_size > 0
    await crawler.close()