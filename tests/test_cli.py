from __future__ import annotations

from pathlib import Path

import pytest
import logging

from crawler.async_crawler import AsyncCrawler
from crawler.cli import parse_args, run
from crawler.cli import build_from_args, parse_args, write_results
from tests.http_fakes import FakeSession
from tests.test_politeness import _crawler, _pages


def test_parse_homework_example() -> None:
    args = parse_args(
        [
            "--urls",
            "https://example.com",
            "--max-pages",
            "100",
            "--output",
            "results.json",
        ]
    )
    assert args.urls == ["https://example.com"]
    assert args.max_pages == 100
    assert args.output == "results.json"
    assert args.respect_robots is None


def test_parse_all_flags() -> None:
    args = parse_args(
        [
            "--urls",
            "https://a.test/",
            "https://b.test/",
            "--max-pages",
            "10",
            "--max-depth",
            "2",
            "--output",
            "out.json",
            "--config",
            "examples/crawler.yaml",
            "--respect-robots",
            "--rate-limit",
            "2.5",
        ]
    )
    assert args.urls == ["https://a.test/", "https://b.test/"]
    assert args.max_depth == 2
    assert args.rate_limit == 2.5
    assert args.respect_robots is True


def test_parse_no_respect_robots() -> None:
    args = parse_args(["--urls", "https://example.com", "--no-respect-robots"])
    assert args.respect_robots is False


def test_cli_requires_urls_or_config() -> None:
    args = parse_args([])
    with pytest.raises(SystemExit, match="Need --urls"):
        build_from_args(args)


def test_cli_overrides_config(tmp_path: Path) -> None:
    cfg = tmp_path / "c.yaml"
    cfg.write_text(
        "crawler:\n  requests_per_second: 1.0\n  respect_robots: true\n"
        "start_urls:\n  - https://from-config.test/\n"
        "crawl:\n  max_pages: 3\n  max_depth: 0\n",
        encoding="utf-8",
    )
    args = parse_args(
        [
            "--config",
            str(cfg),
            "--urls",
            "https://from-cli.test/",
            "--max-pages",
            "9",
            "--rate-limit",
            "4.0",
            "--no-respect-robots",
        ]
    )
    crawler, run_cfg = build_from_args(args)
    assert run_cfg.start_urls == ["https://from-cli.test/"]
    assert run_cfg.max_pages == 9
    assert crawler.requests_per_second == 4.0
    assert crawler.respect_robots is False


def test_write_results_json(tmp_path: Path) -> None:
    crawler = _crawler(FakeSession({}))
    crawler.processed_urls["https://a.test/"] = {
        "url": "https://a.test/",
        "title": "A",
        "text": "hi",
        "status_code": 200,
    }
    path = tmp_path / "results.json"
    write_results(str(path), crawler)
    text = path.read_text(encoding="utf-8")
    assert "https://a.test/" in text
    assert "pages_processed" in text


@pytest.mark.asyncio
async def test_respect_robots_false_fetches_disallowed() -> None:
    pages = _pages("https://a.test/private")
    crawler = _crawler(FakeSession(pages), respect_robots=False)
    body = await crawler.fetch_url("https://a.test/private")
    assert body == "ok"
    assert crawler.blocked_urls == set()
    await crawler.close()

@pytest.mark.asyncio
async def test_run_configures_logging(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "cli.log"
    async def fake_crawl(self, *args, **kwargs):
        logging.getLogger("crawler.cli_probe").info("probe-from-run")
        return {}
    monkeypatch.setattr(AsyncCrawler, "crawl", fake_crawl)
    args = parse_args(
        ["--urls", "https://a.test/", "--log-level", "INFO", "--log-file", str(path)]
    )
    await run(args)
    text = path.read_text(encoding="utf-8")
    assert "probe-from-run" in text
