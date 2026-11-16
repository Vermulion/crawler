"""Command-line interface: python crawler.py --urls ... / python -m crawler."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Sequence

from crawler.async_crawler import AsyncCrawler
from crawler.config import CrawlerConfig, crawler_from_config
from crawler.storage import normalize_page
from crawler.log_setup import setup_logging
from crawler.advanced_crawler import AdvancedCrawler



def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="crawler",
        description="Crawl start URLs (optional YAML/JSON config).",
    )
    parser.add_argument(
        "--urls",
        nargs="+",
        metavar="URL",
        help="Start URLs (overrides config start_urls)",
    )
    parser.add_argument("--max-pages", type=int, default=None)
    parser.add_argument("--max-depth", type=int, default=None)
    parser.add_argument(
        "--output",
        "-o",
        help="Write crawl results JSON to this file",
    )
    parser.add_argument("--config", help="YAML or JSON config file")
    parser.add_argument(
        "--respect-robots",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Follow robots.txt (default: on, or config crawler.respect_robots)",
    )
    parser.add_argument(
        "--rate-limit",
        type=float,
        default=None,
        metavar="RPS",
        help="Requests per second (overrides config)",
    )
    parser.add_argument(
        "--log-level",
        default=None,
        help="DEBUG, INFO, WARNING, or ERROR",
    )
    parser.add_argument(
        "--log-file",
        default=None,
        help="Log file (default crawler.log)",
    )
    return parser.parse_args(argv)


def _json_default(obj: Any) -> str:
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def write_results(path: str, crawler: AsyncCrawler) -> None:
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    pages = {
        url: normalize_page(page)
        for url, page in crawler.processed_urls.items()
    }
    payload = {
        "processed_count": len(pages),
        "failed_count": len(crawler.failed_urls),
        "processed": pages,
        "failed": crawler.failed_urls,
        "stats": crawler.get_crawler_stats(),
    }
    dest.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default) + "\n",
        encoding="utf-8",
    )


def build_from_args(args: argparse.Namespace) -> tuple[AsyncCrawler, CrawlerConfig]:
    cfg: Optional[CrawlerConfig] = None
    if args.config:
        crawler, cfg = crawler_from_config(args.config)
        adv = AdvancedCrawler.from_config(args.config, setup_logs=False)
        crawler, cfg = adv.crawler, adv.cfg

    else:
        crawler = AsyncCrawler()
        cfg = CrawlerConfig(crawler_kwargs={})

    if args.rate_limit is not None:
        if args.rate_limit <= 0:
            raise SystemExit("--rate-limit must be > 0")
        crawler.requests_per_second = args.rate_limit
        crawler.rate_limiter.requests_per_second = args.rate_limit
        crawler.rate_limiter._interval = 1.0 / args.rate_limit
    if args.respect_robots is not None:
        crawler.respect_robots = args.respect_robots

    urls = list(args.urls) if args.urls else list(cfg.start_urls)
    if not urls and not cfg.sitemap_urls:
        raise SystemExit("Need --urls or config start_urls / sitemap_urls")

    cfg.start_urls = urls
    if args.max_pages is not None:
        cfg.max_pages = args.max_pages
    if args.max_depth is not None:
        cfg.max_depth = args.max_depth
    return crawler, cfg


def _apply_logging(args: argparse.Namespace, cfg: CrawlerConfig) -> None:
    setup_logging(
        level=args.log_level or getattr(cfg, "log_level", "INFO"),
        log_file=(
            args.log_file
            if args.log_file is not None
            else getattr(cfg, "log_file", "crawler.log")
        ),
        max_bytes=getattr(cfg, "log_max_bytes", 1_000_000),
        backup_count=getattr(cfg, "log_backup_count", 3),
    )

async def run(args: argparse.Namespace) -> int:
    crawler, cfg = build_from_args(args)
    _apply_logging(args, cfg)
    async with crawler:
        await crawler.crawl(
            cfg.start_urls,
            max_pages=cfg.max_pages,
            max_depth=cfg.max_depth,
            sitemap_urls=cfg.sitemap_urls or None,
        )
        if args.output:
            write_results(args.output, crawler)
            print(f"Saved {args.output}", file=sys.stderr)
        print(
            f"processed={len(crawler.processed_urls)} "
            f"failed={len(crawler.failed_urls)}",
            file=sys.stderr,
        )
    if cfg.storage is not None:
        await cfg.storage.close()
    return 0


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = parse_args(argv)
    raise SystemExit(asyncio.run(run(args)))
