"""Load YAML/JSON crawler config and build AsyncCrawler kwargs."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from crawler.storage import CSVStorage, DataStorage, JSONStorage, PostgresStorage

_CRAWLER_KEYS = frozenset(
    {
        "max_concurrent",
        "max_per_domain",
        "connect_timeout",
        "read_timeout",
        "total_timeout",
        "timeout_backoff_factor",
        "timeout_max",
        "pool_limit",
        "pool_limit_per_host",
        "same_domain_only",
        "include_patterns",
        "exclude_patterns",
        "requests_per_second",
        "rate_limit_per_domain",
        "min_delay",
        "jitter",
        "max_retries",
        "backoff_factor",
        "backoff_max",
        "failure_threshold",
        "failure_window",
        "recovery_timeout",
        "user_agent",
        "user_agents",
        "storage_batch_size",
        "storage_max_retries",
        "storage_backoff_factor",
        "respect_robots",
    }
)


@dataclass
class CrawlerConfig:
    crawler_kwargs: dict[str, Any]
    start_urls: list[str] = field(default_factory=list)
    sitemap_urls: list[str] = field(default_factory=list)
    max_pages: int = 100
    max_depth: Optional[int] = None
    storage: Optional[DataStorage] = None
    log_level: str = "INFO"
    log_file: str | None = "crawler.log"
    log_max_bytes: int = 1_000_000
    log_backup_count: int = 3


def load_config(path: str | Path) -> CrawlerConfig:
    file = Path(path)
    raw = _read_mapping(file)
    base = file.parent

    crawler = dict(raw.get("crawler") or {})
    filters = dict(raw.get("filters") or {})
    crawl = dict(raw.get("crawl") or {})
    storage_raw = dict(raw.get("storage") or {})
    logging_raw = dict(raw.get("logging") or {})

    unknown = set(crawler) - _CRAWLER_KEYS
    if unknown:
        raise ValueError(f"Unknown crawler keys: {sorted(unknown)}")

    if "same_domain_only" in filters:
        crawler["same_domain_only"] = filters["same_domain_only"]
    if filters.get("include_patterns") is not None:
        crawler["include_patterns"] = list(filters["include_patterns"])
    exclude = filters.get("exclude_patterns")
    if exclude is None:
        exclude = raw.get("exceptions")  # homework name for blacklist
    if exclude is not None:
        crawler["exclude_patterns"] = list(exclude)

    storage = _build_storage(storage_raw, base)
    if "batch_size" in storage_raw:
        crawler["storage_batch_size"] = int(storage_raw["batch_size"])
    if "max_retries" in storage_raw:
        crawler["storage_max_retries"] = int(storage_raw["max_retries"])
    if "backoff_factor" in storage_raw:
        crawler["storage_backoff_factor"] = float(storage_raw["backoff_factor"])
    if storage is not None:
        crawler["storage"] = storage

    depth = crawl.get("max_depth")
    return CrawlerConfig(
        crawler_kwargs=crawler,
        start_urls=list(raw.get("start_urls") or []),
        sitemap_urls=list(raw.get("sitemap_urls") or []),
        max_pages=int(crawl.get("max_pages") or 100),
        max_depth=None if depth is None else int(depth),
        storage=storage,
        log_level=str(logging_raw.get("level") or "INFO"),
        log_file=logging_raw.get("file", "crawler.log"),
        log_max_bytes=int(logging_raw.get("max_bytes") or 1_000_000),
        log_backup_count=int(logging_raw.get("backup_count") or 3),
    )


def crawler_from_config(path: str | Path):
    """Build AsyncCrawler from a YAML/JSON file. Does not start the crawl."""
    from crawler.async_crawler import AsyncCrawler

    cfg = load_config(path)
    return AsyncCrawler(**cfg.crawler_kwargs), cfg


def _read_mapping(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    if suffix == ".json":
        data = json.loads(text)
    elif suffix in {".yml", ".yaml"}:
        import yaml

        data = yaml.safe_load(text)
    else:
        raise ValueError(f"Config must be .json, .yml, or .yaml, got {path.suffix!r}")
    if not isinstance(data, dict):
        raise ValueError("Config root must be a mapping/object")
    return data


def _resolve(base: Path, maybe_path: str) -> Path:
    p = Path(maybe_path)
    return p if p.is_absolute() else (base / p)


def _build_storage(raw: dict, base: Path) -> Optional[DataStorage]:
    kind = str(raw.get("type") or "none").lower()
    if kind in {"", "none", "null"}:
        return None
    if kind == "json":
        path = raw.get("path") or "results.jsonl"
        indent = raw.get("indent", 2)
        return JSONStorage(_resolve(base, path), indent=indent)
    if kind == "csv":
        path = raw.get("path") or "results.csv"
        return CSVStorage(_resolve(base, path), encoding=raw.get("encoding", "utf-8"))
    if kind == "postgres":
        dsn = raw.get("dsn") or ""
        if not dsn:
            raise ValueError("storage.dsn is required for type postgres")
        return PostgresStorage(dsn, table=raw.get("table") or "pages")
    raise ValueError(f"Unknown storage.type: {kind!r}")