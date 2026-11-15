from crawler.async_crawler import AsyncCrawler
from crawler.crawler_queue import CrawlerQueue


def test_bar_and_eta_format() -> None:
    assert AsyncCrawler._bar(0, 100, width=10) == "----------"
    assert AsyncCrawler._bar(100, 100, width=10) == "##########"
    assert AsyncCrawler._format_eta(None) == "--"
    assert AsyncCrawler._format_eta(65) == "1:05"


def test_snapshot_eta_and_active() -> None:
    crawler = AsyncCrawler(requests_per_second=1000.0, min_delay=0.0, jitter=0.0)
    queue = CrawlerQueue(["https://a.test/", "https://b.test/"], max_pages=10)
    start = 100.0  # fake; we patch monotonic below
    import time
    real = time.monotonic
    time.monotonic = lambda: start + 2.0  # 2 seconds later
    try:
        queue._processed.add("https://a.test/")
        queue._pending.clear()
        queue._in_progress.add("https://b.test/")
        snap = crawler._progress_snapshot(queue, start=start)
    finally:
        time.monotonic = real
    assert snap["processed"] == 1
    assert snap["active"] == 1
    assert snap["cap"] == 2
    assert snap["speed"] == 0.5  # 1 page / 2 s
    assert snap["eta"] == 2.0        # 1 remaining / 0.5 pages/s

def test_finished_crawl_is_100_percent() -> None:
    crawler = AsyncCrawler(requests_per_second=1000.0, min_delay=0.0, jitter=0.0)
    queue = CrawlerQueue(["https://a.test/"], max_pages=20)
    queue._pending.clear()
    queue._processed.add("https://a.test/")
    snap = crawler._progress_snapshot(queue, start=0.0)
    assert snap["cap"] == 1
    assert snap["done"] == 1
    assert snap["remaining"] if False else (snap["pending"] + snap["active"] == 0)
    assert crawler._bar(snap["done"], snap["cap"], width=10) == "##########"