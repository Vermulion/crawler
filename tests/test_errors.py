from __future__ import annotations

import asyncio

import aiohttp
import pytest

from crawler.errors import (
    CrawlerError,
    NetworkError,
    ParseError,
    PermanentError,
    TransientError,
    classify_exception,
    classify_status,
)


def test_tree() -> None:
    assert issubclass(TransientError, CrawlerError)
    assert issubclass(PermanentError, CrawlerError)
    assert issubclass(NetworkError, TransientError)
    assert issubclass(ParseError, CrawlerError)
    assert not issubclass(ParseError, PermanentError)
    assert not issubclass(PermanentError, TransientError)


def test_http_classes() -> None:
    assert isinstance(classify_status(401, "u"), PermanentError)
    assert isinstance(classify_status(403, "u"), PermanentError)
    assert isinstance(classify_status(404, "u"), PermanentError)
    assert isinstance(classify_status(429, "u"), TransientError)
    assert isinstance(classify_status(503, "u"), TransientError)


def test_timeout_is_network_and_retryable() -> None:
    err = classify_exception(asyncio.TimeoutError(), url="https://a.test/")
    assert isinstance(err, NetworkError)
    assert isinstance(err, TransientError)


def test_parse_error_is_not_retryable() -> None:
    err = ParseError("bad html", url="https://a.test/")
    assert isinstance(err, CrawlerError)
    assert not isinstance(err, TransientError)