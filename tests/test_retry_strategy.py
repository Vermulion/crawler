from __future__ import annotations

import pytest

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