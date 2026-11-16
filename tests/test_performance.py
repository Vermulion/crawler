import time
import pytest

from crawler import AsyncCrawler
from crawler.sync_crawler import SyncCrawler
from tests.http_fakes import FakeSession
from tests.test_crawl import _crawl_with_pages, _page
import tracemalloc


def _fanout(n: int):
    """One home page that links to n-1 children. Good for parallel crawl."""
    home = "https://site.test/"
    kids = [f"https://site.test/p{i}" for i in range(n - 1)]
    mapping = {home: _page(home, *kids)}
    for url in kids:
        mapping[url] = _page(url)
    return home, mapping


DELAY = 0.02
N = 40

def _fast_kw():
    return dict(
        max_concurrent=20,
        max_per_domain=20,
        requests_per_second=10_000,
        min_delay=0.0,
        jitter=0.0,
        respect_robots=False,
    )

@pytest.mark.asyncio
async def test_async_faster_than_sync() -> None:
    home, mapping = _fanout(N)

    def get_html(url: str) -> str:
        time.sleep(DELAY)           # sync: waits add up
        return mapping[url]._text

    sync = SyncCrawler(get_html)
    t0 = time.perf_counter()
    sync.crawl([home], max_pages=N)
    sync_sec = time.perf_counter() - t0

    crawler = AsyncCrawler(
        max_concurrent=10,
        max_per_domain=10,
        requests_per_second=10_000,
        min_delay=0,
        jitter=0,
        respect_robots=False,
    )
    crawler._session = FakeSession(mapping, delay=DELAY)
    t1 = time.perf_counter()
    await crawler.crawl([home], max_pages=N, max_depth=1)
    async_sec = time.perf_counter() - t1
    speedup = sync_sec / async_sec
    saved = sync_sec - async_sec
    print(
        f"\n  pages={N}  delay={DELAY}s\n"
        f"  sync={sync_sec:.3f}s  async={async_sec:.3f}s\n"
        f"  speedup={speedup:.1f}x  saved={saved:.3f}s"
    )
    await crawler.close()

    assert len(sync.processed_urls) == N
    assert len(crawler.processed_urls) == N
    assert async_sec * 2 < sync_sec

@pytest.mark.asyncio
async def test_memory_grows_roughly_linear() -> None:
    peaks: dict[int, int] = {}
    for n in (100, 1000):
        home, mapping = _fanout(n)
        tracemalloc.start()
        crawler, _session = await _crawl_with_pages(
            mapping, [home], max_pages=n, max_depth=1, **_fast_kw()
        )
        _current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        peaks[n] = peak
        assert len(crawler.processed_urls) == n
        await crawler.close()

    # 10× pages should not be 100× RAM (that would mean a leak / quadratic)
    assert peaks[1000] / peaks[100] < 20
    print(f"peak 100={peaks[100]}  peak 1000={peaks[1000]}")  # pytest -s to see it

@pytest.mark.parametrize("n", [100, 500, 1000])
@pytest.mark.asyncio
async def test_scales_to_n_pages(n: int) -> None:
    home, mapping = _fanout(n)
    t0 = time.perf_counter()
    crawler, _session = await _crawl_with_pages(
        mapping, [home], max_pages=n, max_depth=1, **_fast_kw()
    )
    elapsed = time.perf_counter() - t0
    assert len(crawler.processed_urls) == n
    assert elapsed < 15
    await crawler.close()