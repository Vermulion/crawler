"""Keep the 'crawler' logger from leaking setup_logging() into other tests."""

from __future__ import annotations

import logging
from collections.abc import Iterator

import pytest


def _reset_crawler_logger() -> None:
    log = logging.getLogger("crawler")
    for handler in log.handlers[:]:
        log.removeHandler(handler)
        handler.close()
    log.propagate = True
    log.setLevel(logging.NOTSET)


@pytest.fixture(autouse=True)
def reset_crawler_logger() -> Iterator[None]:
    _reset_crawler_logger()
    yield
    _reset_crawler_logger()
