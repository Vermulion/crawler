from __future__ import annotations

import pytest

from crawler.errors import PermanentError, TransientError
from crawler.retry_strategy import RetryStrategy


@pytest.mark.asyncio
async def test_retries_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr("crawler.retry_strategy.asyncio.sleep", fake_sleep)

    calls = {"n": 0}

    async def flaky() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise TimeoutError("temporary")
        return "ok"

    strategy = RetryStrategy(
        max_retries=3,
        backoff_factor=2.0,
        retry_on=[TimeoutError],
    )
    result = await strategy.execute_with_retry(flaky)

    assert result == "ok"
    assert calls["n"] == 3          # 1 fail + 1 fail + 1 success
    assert sleeps == [2.0, 4.0]     # wait after each failure, not after success


@pytest.mark.asyncio
async def test_exponential_backoff_doubles_each_wait(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr("crawler.retry_strategy.asyncio.sleep", fake_sleep)

    async def always_fail() -> str:
        raise TimeoutError("temporary")

    strategy = RetryStrategy(
        max_retries=3,
        backoff_factor=2.0,
        retry_on=[TimeoutError],
    )
    with pytest.raises(TimeoutError):
        await strategy.execute_with_retry(always_fail)
    assert sleeps == [2.0, 4.0, 8.0]


def test_should_retry_404_no_503_yes() -> None:
    strategy = RetryStrategy()
    assert strategy.should_retry(PermanentError("gone", url="u", status=404)) is False
    assert strategy.should_retry(TransientError("down", url="u", status=503)) is True