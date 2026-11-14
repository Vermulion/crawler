from __future__ import annotations

from pathlib import Path

import pytest

from crawler.config import crawler_from_config, load_config
from crawler.storage import JSONStorage, PostgresStorage


def test_load_json_config(tmp_path: Path) -> None:
    path = tmp_path / "crawler.json"
    path.write_text(
        """
        {
          "crawler": {"max_concurrent": 3, "requests_per_second": 2.5},
          "start_urls": ["https://a.test/"],
          "filters": {"same_domain_only": false, "exclude_patterns": ["\\\\.pdf$"]},
          "crawl": {"max_pages": 7, "max_depth": 2},
          "storage": {"type": "json", "path": "out.jsonl", "batch_size": 4}
        }
        """,
        encoding="utf-8",
    )
    cfg = load_config(path)
    assert cfg.start_urls == ["https://a.test/"]
    assert cfg.max_pages == 7
    assert cfg.max_depth == 2
    assert cfg.crawler_kwargs["max_concurrent"] == 3
    assert cfg.crawler_kwargs["same_domain_only"] is False
    assert cfg.crawler_kwargs["exclude_patterns"] == [r"\.pdf$"]
    assert cfg.crawler_kwargs["storage_batch_size"] == 4
    assert isinstance(cfg.storage, JSONStorage)
    assert cfg.storage.path == tmp_path / "out.jsonl"


def test_load_yaml_config(tmp_path: Path) -> None:
    path = tmp_path / "crawler.yaml"
    path.write_text(
        "crawler:\n  max_concurrent: 4\nstart_urls:\n  - https://b.test/\n"
        "exceptions:\n  - /secret\nstorage:\n  type: none\n",
        encoding="utf-8",
    )
    crawler, cfg = crawler_from_config(path)
    assert crawler.max_concurrent == 4
    assert cfg.start_urls == ["https://b.test/"]
    assert crawler.exclude_patterns == ["/secret"]
    assert crawler.storage is None


def test_load_yaml_postgres_storage(tmp_path: Path) -> None:
    path = tmp_path / "crawler.yaml"
    path.write_text(
        "start_urls:\n  - https://a.test/\n"
        "storage:\n"
        "  type: postgres\n"
        "  dsn: postgresql://crawler:crawler@localhost:5432/crawler\n"
        "  table: pages\n",
        encoding="utf-8",
    )
    cfg = load_config(path)
    assert isinstance(cfg.storage, PostgresStorage)
    assert cfg.storage.dsn.startswith("postgresql://")
    assert cfg.storage.table == "pages"


def test_unknown_crawler_key(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text('{"crawler": {"max_concurent": 1}}', encoding="utf-8")
    with pytest.raises(ValueError, match="Unknown crawler keys"):
        load_config(path)