from __future__ import annotations

import logging
from pathlib import Path

from crawler.log_setup import setup_logging


def test_writes_timestamp_to_file_and_logger_level(tmp_path: Path) -> None:
    path = tmp_path / "crawler.log"
    setup_logging(level="DEBUG", log_file=str(path), max_bytes=10_000, backup_count=2)
    log = logging.getLogger("crawler.test_log")
    log.debug("hello-debug")
    log.info("hello-info")
    text = path.read_text(encoding="utf-8")
    assert "hello-debug" in text
    assert "hello-info" in text
    assert "DEBUG" in text
    assert "INFO" in text
    # timestamp like 2026-11-15 00:15:01
    assert text[:4].isdigit()


def test_info_hides_debug(tmp_path: Path) -> None:
    path = tmp_path / "crawler.log"
    setup_logging(level="INFO", log_file=str(path))
    logging.getLogger("crawler.x").debug("secret")
    logging.getLogger("crawler.x").warning("visible")
    text = path.read_text(encoding="utf-8")
    assert "secret" not in text
    assert "visible" in text


def test_rotation_creates_backup(tmp_path: Path) -> None:
    path = tmp_path / "crawler.log"
    setup_logging(level="INFO", log_file=str(path), max_bytes=200, backup_count=2)
    log = logging.getLogger("crawler.rot")
    for i in range(50):
        log.info("line-%s-%s", i, "x" * 40)
    for h in logging.getLogger("crawler").handlers:
        h.flush()
    backups = list(tmp_path.glob("crawler.log*"))
    assert len(backups) >= 2