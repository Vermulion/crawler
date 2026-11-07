from __future__ import annotations

import time

import pytest

from crawler.circuit_breaker import CLOSED, HALF_OPEN, OPEN, CircuitBreaker
from crawler.errors import CircuitOpenError, TransientError
from crawler import AsyncCrawler
from tests.http_fakes import FakeResponse, FakeSession
from tests.test_crawler_retry import _crawler


def test_opens_after_threshold() -> None:
    br = CircuitBreaker(failure_threshold=3, failure_window=60.0, recovery_timeout=30.0)
    assert br.allow("a.test") is True
    br.record_failure("a.test")
    br.record_failure("a.test")
    assert br.state("a.test") == CLOSED
    br.record_failure("a.test")
    assert br.state("a.test") == OPEN
    assert br.allow("a.test") is False


def test_recovers_after_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    br = CircuitBreaker(failure_threshold=1, failure_window=60.0, recovery_timeout=10.0)
    br.record_failure("a.test")
    assert br.allow("a.test") is False

    start = time.monotonic()
    monkeypatch.setattr("crawler.circuit_breaker.time.monotonic", lambda: start + 11.0)
    assert br.allow("a.test") is True
    assert br.state("a.test") == HALF_OPEN
    br.record_success("a.test")
    assert br.state("a.test") == CLOSED


def test_half_open_failure_opens_again(monkeypatch: pytest.MonkeyPatch) -> None:
    br = CircuitBreaker(failure_threshold=1, failure_window=60.0, recovery_timeout=5.0)
    br.record_failure("a.test")
    start = time.monotonic()
    monkeypatch.setattr("crawler.circuit_breaker.time.monotonic", lambda: start + 6.0)
    assert br.allow("a.test") is True
    br.record_failure("a.test")
    assert br.state("a.test") == OPEN


@pytest.mark.asyncio
async def test_crawler_skips_domain_when_open() -> None:
    url = "https://a.test/x"
    session = FakeSession(
        {
            url: FakeResponse("nope", status=503, url=url),
            "https://a.test/robots.txt": FakeResponse("User-agent: *\nAllow: /"),
        }
    )
    crawler = _crawler(
        session,
        max_retries=0,
        failure_threshold=2,
        failure_window=60.0,
        recovery_timeout=30.0,
    )
    with pytest.raises(TransientError):
        await crawler.fetch_url(url)
    with pytest.raises(TransientError):
        await crawler.fetch_url(url)
    with pytest.raises(CircuitOpenError):
        await crawler.fetch_url(url)
    # third call must not hit the network
    assert session.calls.count(url) == 2
    await crawler.close()