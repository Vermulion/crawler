"""One entry point: config + logging + crawl + storage + stats."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from crawler.async_crawler import AsyncCrawler
from crawler.config import CrawlerConfig, crawler_from_config, load_config
from crawler.log_setup import setup_logging


class AdvancedCrawler:
    """Facade around AsyncCrawler plus config, logs, and stats export."""

    def __init__(
        self,
        crawler: AsyncCrawler,
        cfg: CrawlerConfig,
        *,
        setup_logs: bool = True,
    ) -> None:
        self.crawler = crawler
        self.cfg = cfg
        if setup_logs:
            setup_logging(
                level=cfg.log_level,
                log_file=cfg.log_file,
                max_bytes=cfg.log_max_bytes,
                backup_count=cfg.log_backup_count,
            )

    @classmethod
    def from_config(
        cls,
        path: str | Path,
        *,
        setup_logs: bool = True,
    ) -> "AdvancedCrawler":
        crawler, cfg = crawler_from_config(path)
        return cls(crawler, cfg, setup_logs=setup_logs)

    @classmethod
    def from_kwargs(
        cls,
        *,
        setup_logs: bool = False,
        log_level: str = "INFO",
        log_file: str | None = None,
        **crawler_kwargs: Any,
    ) -> "AdvancedCrawler":
        cfg = CrawlerConfig(
            crawler_kwargs=dict(crawler_kwargs),
            log_level=log_level,
            log_file=log_file,
        )
        return cls(AsyncCrawler(**crawler_kwargs), cfg, setup_logs=setup_logs)

    async def crawl(
        self,
        start_urls: Optional[list[str]] = None,
        max_pages: Optional[int] = None,
        *,
        max_depth: Optional[int] = None,
        sitemap_urls: Optional[list[str]] = None,
    ) -> dict[str, dict]:
        urls = list(start_urls) if start_urls is not None else list(self.cfg.start_urls)
        maps = (
            list(sitemap_urls)
            if sitemap_urls is not None
            else list(self.cfg.sitemap_urls)
        )
        return await self.crawler.crawl(
            urls,
            max_pages=self.cfg.max_pages if max_pages is None else max_pages,
            max_depth=self.cfg.max_depth if max_depth is None else max_depth,
            sitemap_urls=maps or None,
        )

    def get_stats(self) -> dict:
        return self.crawler.get_crawler_stats()

    def export_stats(
        self,
        *,
        json_path: str | None = None,
        html_path: str | None = None,
        charts_dir: str | None = None,
    ) -> dict[str, str]:
        """Write stats JSON / HTML / PNG. Paths you pass are created."""
        out: dict[str, str] = {}
        stats = self.crawler.stats
        if json_path:
            out["json"] = stats.export_to_json(json_path)
        if html_path:
            out["html"] = stats.export_to_html_report(html_path)
        if charts_dir:
            out.update(stats.export_charts(charts_dir))
        return out

    async def close(self) -> None:
        await self.crawler.close()
        if self.cfg.storage is not None:
            await self.cfg.storage.close()

    async def __aenter__(self) -> "AdvancedCrawler":
        await self.crawler.__aenter__()
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()