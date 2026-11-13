"""Offline crawl tests: depth limit, filters, unique visited_urls."""

from __future__ import annotations

import json
import asyncio
from pathlib import Path

import pytest

from crawler import AsyncCrawler
from crawler.storage import RECORD_FIELDS, DataStorage, JSONStorage
from tests.http_fakes import FakeResponse, FakeSession

class ListStorage(DataStorage):
    """In-memory backend so tests stay offline."""
    def __init__(self) -> None:
        self.saved: list[dict] = []
        self.batch_sizes: list[int] = []
    async def save(self, data: dict) -> None:
        self.saved.append(data)
    async def save_many(self, rows: list[dict]) -> None:
        self.batch_sizes.append(len(rows))
        for row in rows:
            await self.save(row)
    async def close(self) -> None:
        return None

@pytest.mark.asyncio
async def test_crawl_saves_each_page() -> None:
    mapping = {
        "https://site.test/": _page("https://site.test/", "https://site.test/b"),
        "https://site.test/b": _page("https://site.test/b"),
    }
    storage = ListStorage()
    crawler, _session = await _crawl_with_pages(
        mapping,
        ["https://site.test/"],
        max_depth=1,
        storage=storage,
        storage_batch_size=1,
    )
    urls = {row["url"] for row in storage.saved}
    assert urls == {"https://site.test/", "https://site.test/b"}
    assert storage.batch_sizes == [1, 1]
    assert storage.saved[0]["status_code"] == 200
    assert "text/html" in storage.saved[0]["content_type"]
    await crawler.close()

@pytest.mark.asyncio
async def test_crawl_batch_save() -> None:
    mapping = {
        "https://site.test/": _page("https://site.test/", "https://site.test/b"),
        "https://site.test/b": _page("https://site.test/b"),
    }
    storage = ListStorage()
    crawler, _session = await _crawl_with_pages(
        mapping,
        ["https://site.test/"],
        max_depth=1,
        storage=storage,
        storage_batch_size=2,
    )
    assert len(storage.saved) == 2
    assert storage.batch_sizes == [2]
    await crawler.close()


@pytest.mark.asyncio
async def test_crawl_json_record_integrity(tmp_path: Path) -> None:
    mapping = {"https://site.test/": _page("https://site.test/")}
    path = tmp_path / "out.jsonl"
    storage = JSONStorage(path, indent=None, buffer_bytes=1)
    crawler, _session = await _crawl_with_pages(
        mapping,
        ["https://site.test/"],
        max_depth=0,
        storage=storage,
        storage_batch_size=1,
    )
    await storage.close()
    rec = json.loads(path.read_text(encoding="utf-8").strip())
    assert set(rec) == set(RECORD_FIELDS)
    assert rec["url"] == "https://site.test/"
    assert rec["status_code"] == 200
    assert rec["title"]
    assert "crawled_at" in rec
    await crawler.close()

def _page(url: str, *hrefs: str) -> FakeResponse:
    anchors = "".join(f'<a href="{href}">{href}</a>' for href in hrefs)
    html = f"<html><head><title>{url}</title></head><body>{anchors}</body></html>"
    return FakeResponse(html, url=url)


async def _crawl_with_pages(
    mapping: dict[str, FakeResponse],
    start: list[str],
    *,
    max_pages: int = 20,
    max_depth: int | None = None,
    **crawler_kw,
) -> tuple[AsyncCrawler, FakeSession]:
    crawler_kw.setdefault("max_concurrent", 2)
    crawler_kw.setdefault("requests_per_second", 1000.0)
    crawler_kw.setdefault("min_delay", 0.0)
    crawler_kw.setdefault("jitter", 0.0)
    crawler = AsyncCrawler(**crawler_kw)
    session = FakeSession(mapping)
    crawler._session = session  # type: ignore[assignment]
    await crawler.crawl(start, max_pages=max_pages, max_depth=max_depth)
    return crawler, session


@pytest.mark.asyncio
async def test_max_depth_does_not_follow_too_deep() -> None:
    mapping = {
        "https://site.test/": _page("https://site.test/", "https://site.test/b"),
        "https://site.test/b": _page("https://site.test/b", "https://site.test/c"),
        "https://site.test/c": _page("https://site.test/c"),
    }
    crawler, session = await _crawl_with_pages(
        mapping, ["https://site.test/"], max_depth=1
    )
    assert "https://site.test/" in crawler.processed_urls
    assert "https://site.test/b" in crawler.processed_urls
    assert "https://site.test/c" not in crawler.processed_urls
    assert "https://site.test/c" not in crawler.visited_urls
    assert "https://site.test/c" not in session.calls
    await crawler.close()


@pytest.mark.asyncio
async def test_visited_urls_has_no_duplicates() -> None:
    mapping = {
        "https://site.test/": _page(
            "https://site.test/",
            "https://site.test/b",
            "https://site.test/b",
            "https://site.test/",
        ),
        "https://site.test/b": _page("https://site.test/b", "https://site.test/"),
    }
    crawler, session = await _crawl_with_pages(
        mapping,
        ["https://site.test/", "https://site.test/"],
        max_depth=2,
    )
    assert len(crawler.visited_urls) == len(set(crawler.visited_urls))
    assert session.calls.count("https://site.test/") == 1
    assert session.calls.count("https://site.test/b") == 1
    await crawler.close()


@pytest.mark.asyncio
async def test_crawl_respects_exclude_blacklist() -> None:
    mapping = {
        "https://site.test/": _page(
            "https://site.test/",
            "https://site.test/ok",
            "https://site.test/secret.pdf",
        ),
        "https://site.test/ok": _page("https://site.test/ok"),
        "https://site.test/secret.pdf": _page("https://site.test/secret.pdf"),
    }
    crawler, _session = await _crawl_with_pages(
        mapping,
        ["https://site.test/"],
        max_depth=1,
        exclude_patterns=[r"\.pdf$"],
    )
    assert "https://site.test/ok" in crawler.processed_urls
    assert "https://site.test/secret.pdf" not in crawler.visited_urls
    assert "https://site.test/secret.pdf" not in crawler.processed_urls
    await crawler.close()


@pytest.mark.asyncio
async def test_crawl_respects_include_whitelist() -> None:
    mapping = {
        "https://site.test/blog": _page(
            "https://site.test/blog",
            "https://site.test/blog/post",
            "https://site.test/about",
        ),
        "https://site.test/blog/post": _page("https://site.test/blog/post"),
        "https://site.test/about": _page("https://site.test/about"),
    }
    crawler, _session = await _crawl_with_pages(
        mapping,
        ["https://site.test/blog"],
        max_depth=1,
        include_patterns=[r"/blog"],
    )
    assert "https://site.test/blog" in crawler.processed_urls
    assert "https://site.test/blog/post" in crawler.processed_urls
    assert "https://site.test/about" not in crawler.visited_urls
    await crawler.close()

class FlakyStorage(ListStorage):
    def __init__(self, fail_times: int) -> None:
        super().__init__()
        self.fail_times = fail_times
        self.calls = 0

    async def save_many(self, rows: list[dict]) -> None:
        self.calls += 1
        if self.calls <= self.fail_times:
            raise OSError("disk full")
        await super().save_many(rows)


@pytest.mark.asyncio
async def test_storage_retries_then_succeeds(caplog: pytest.LogCaptureFixture) -> None:
    mapping = {"https://site.test/": _page("https://site.test/")}
    storage = FlakyStorage(fail_times=2)
    with caplog.at_level("WARNING", logger="crawler.async_crawler"):
        crawler, _session = await _crawl_with_pages(
            mapping,
            ["https://site.test/"],
            max_depth=0,
            storage=storage,
            storage_batch_size=1,
            storage_max_retries=3,
            storage_backoff_factor=0.0,
        )
    assert len(storage.saved) == 1
    assert storage.calls == 3
    assert crawler.storage_errors == []
    assert "Storage save failed" in caplog.text
    await crawler.close()


class FlakyFlushStorage(ListStorage):
    def __init__(self, fail_times: int) -> None:
        super().__init__()
        self.fail_times = fail_times
        self.flush_calls = 0

    async def flush(self) -> None:
        self.flush_calls += 1
        if self.flush_calls <= self.fail_times:
            raise OSError("flush failed")


@pytest.mark.asyncio
async def test_storage_flush_retries_then_succeeds(
    caplog: pytest.LogCaptureFixture,
) -> None:
    mapping = {"https://site.test/": _page("https://site.test/")}
    storage = FlakyFlushStorage(fail_times=2)
    with caplog.at_level("WARNING", logger="crawler.async_crawler"):
        crawler, _session = await _crawl_with_pages(
            mapping,
            ["https://site.test/"],
            max_depth=0,
            storage=storage,
            storage_batch_size=1,
            storage_max_retries=3,
            storage_backoff_factor=0.0,
        )
    assert len(storage.saved) == 1
    assert storage.flush_calls == 3
    assert crawler.storage_errors == []
    assert "Storage flush failed" in caplog.text
    await crawler.close()


@pytest.mark.asyncio
async def test_crawl_continues_when_storage_fails(caplog: pytest.LogCaptureFixture) -> None:
    mapping = {
        "https://site.test/": _page("https://site.test/", "https://site.test/b"),
        "https://site.test/b": _page("https://site.test/b"),
    }
    storage = FlakyStorage(fail_times=99)
    with caplog.at_level("ERROR", logger="crawler.async_crawler"):
        crawler, _session = await _crawl_with_pages(
            mapping,
            ["https://site.test/"],
            max_depth=1,
            storage=storage,
            storage_batch_size=1,
            storage_max_retries=1,
            storage_backoff_factor=0.0,
        )
    assert "https://site.test/" in crawler.processed_urls
    assert "https://site.test/b" in crawler.processed_urls
    assert storage.saved == []
    assert crawler.storage_errors
    assert "Storage save gave up" in caplog.text
    await crawler.close()

@pytest.mark.asyncio
async def test_crawler_close_flushes_json_file(tmp_path: Path) -> None:
    mapping = {"https://site.test/": _page("https://site.test/")}
    path = tmp_path / "out.jsonl"
    storage = JSONStorage(path, indent=None, buffer_bytes=1_000_000)
    crawler, _session = await _crawl_with_pages(
        mapping,
        ["https://site.test/"],
        max_depth=0,
        storage=storage,
        storage_batch_size=1,
    )
    await crawler.close()
    rec = json.loads(path.read_text(encoding="utf-8").strip())
    assert rec["url"] == "https://site.test/"
    await storage.close()

class OverlapStorage(DataStorage):
    def __init__(self) -> None:
        self.saved: list[dict] = []
        self._in_flight = 0
        self.max_in_flight = 0

    async def save(self, data: dict) -> None:
        await self.save_many([data])

    async def save_many(self, rows: list[dict]) -> None:
        self._in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self._in_flight)
        await asyncio.sleep(0.02)
        self.saved.extend(rows)
        self._in_flight -= 1

    async def close(self) -> None:
        return None

@pytest.mark.asyncio
async def test_storage_saves_are_serialized() -> None:
    urls = [f"https://site.test/p{i}" for i in range(6)]
    mapping = {url: _page(url) for url in urls}
    storage = OverlapStorage()
    crawler, _session = await _crawl_with_pages(
        mapping,
        urls,
        max_pages=6,
        max_depth=0,
        max_concurrent=4,
        storage=storage,
        storage_batch_size=1,
    )
    await crawler.close()
    assert storage.max_in_flight == 1
    assert {row["url"] for row in storage.saved} == set(urls)