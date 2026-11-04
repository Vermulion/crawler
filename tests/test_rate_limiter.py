"""Offline tests for RateLimiter: one domain, several domains, delay floor."""

from __future__ import annotations

import asyncio
import time

import pytest

from crawler.rate_limiter import RateLimiter


async def _stamp(limiter: RateLimiter, domain: str) -> float:
    await limiter.acquire(domain)
    return time.monotonic()


@pytest.mark.asyncio
async def test_same_domain_waits_between_requests() -> None:
    limiter = RateLimiter(requests_per_second=5.0, per_domain=True, jitter=0.0)
    t0 = time.monotonic()
    times = await asyncio.gather(
        _stamp(limiter, "a.test"),
        _stamp(limiter, "a.test"),
        _stamp(limiter, "a.test"),
    )
    elapsed = time.monotonic() - t0
    times.sort()
    assert times[1] - times[0] == pytest.approx(0.2, abs=0.08)
    assert times[2] - times[1] == pytest.approx(0.2, abs=0.08)
    assert elapsed == pytest.approx(0.4, abs=0.12)


@pytest.mark.asyncio
async def test_several_domains_run_on_separate_clocks() -> None:
    limiter = RateLimiter(requests_per_second=5.0, per_domain=True, jitter=0.0)
    t0 = time.monotonic()
    await asyncio.gather(
        _stamp(limiter, "a.test"),
        _stamp(limiter, "b.test"),
        _stamp(limiter, "c.test"),
    )
    assert time.monotonic() - t0 < 0.12


@pytest.mark.asyncio
async def test_global_limit_shares_one_clock_across_domains() -> None:
    limiter = RateLimiter(requests_per_second=5.0, per_domain=False, jitter=0.0)
    t0 = time.monotonic()
    times = await asyncio.gather(
        _stamp(limiter, "a.test"),
        _stamp(limiter, "b.test"),
    )
    elapsed = time.monotonic() - t0
    times.sort()
    assert times[1] - times[0] == pytest.approx(0.2, abs=0.08)
    assert elapsed == pytest.approx(0.2, abs=0.12)


@pytest.mark.asyncio
async def test_min_delay_is_the_floor_when_rate_is_faster() -> None:
    limiter = RateLimiter(
        requests_per_second=100.0,
        per_domain=True,
        min_delay=0.25,
        jitter=0.0,
    )
    t0 = time.monotonic()
    await limiter.acquire("a.test")
    await limiter.acquire("a.test")
    assert time.monotonic() - t0 == pytest.approx(0.25, abs=0.08)


def test_rejects_non_positive_rate() -> None:
    with pytest.raises(ValueError):
        RateLimiter(requests_per_second=0)
    with pytest.raises(ValueError):
        RateLimiter(min_delay=-1)
