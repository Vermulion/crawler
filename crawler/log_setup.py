"""Console + rotating file logging with timestamps."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"


def setup_logging(
    *,
    level: str = "INFO",
    log_file: str | None = "crawler.log",
    max_bytes: int = 1_000_000,
    backup_count: int = 3,
) -> logging.Logger:
    """Attach stderr + optional rotating file to the 'crawler' logger."""
    numeric = getattr(logging, str(level).upper(), None)
    if not isinstance(numeric, int):
        raise ValueError(f"Unknown log level: {level!r}")

    log = logging.getLogger("crawler")
    log.setLevel(numeric)
    log.handlers.clear()
    log.propagate = False

    formatter = logging.Formatter(_FORMAT, datefmt=_DATEFMT)

    console = logging.StreamHandler()
    console.setLevel(numeric)
    console.setFormatter(formatter)
    log.addHandler(console)

    if log_file:
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            path,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setLevel(numeric)
        file_handler.setFormatter(formatter)
        log.addHandler(file_handler)

    return log