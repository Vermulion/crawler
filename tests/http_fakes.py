"""Offline fake aiohttp session for tests (no network)."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import aiohttp


def http_error(status: int, url: str = "https://x.test") -> aiohttp.ClientResponseError:
    request_info = MagicMock()
    request_info.real_url = url
    return aiohttp.ClientResponseError(
        request_info,
        (),
        status=status,
        message=f"HTTP {status}",
    )


class FakeResponse:
    def __init__(self, text: str, status: int = 200, url: str = "https://x.test") -> None:
        self._text = text
        self.status = status
        self._url = url

    async def text(self) -> str:
        return self._text

    def raise_for_status(self) -> None:
        if self.status >= 400:
            raise http_error(self.status, self._url)


class FakeSession:
    def __init__(
        self,
        mapping: dict[str, FakeResponse],
        delay: float = 0.0,
        errors: dict[str, BaseException] | None = None,
        fail_counts: dict[str, int] | None = None,
    ) -> None:
        self.mapping = mapping
        self.delay = delay
        self.errors = errors or {}
        self.closed = False
        self.calls: list[str] = []
        self.request_headers: list[dict] = []
        self.inflight = 0
        self.max_inflight = 0
        self.request_timeouts: list = []
        self.fail_counts = dict(fail_counts or {})

    def get(self, url: str, headers=None, **kwargs) -> "_DelayedResponse":
        self.calls.append(url)
        self.request_headers.append(dict(headers or {}))
        self.request_timeouts.append(kwargs.get("timeout"))
        return _DelayedResponse(self, url)

    async def close(self) -> None:
        self.closed = True


class _DelayedResponse:
    def __init__(self, session: FakeSession, url: str) -> None:
        self._session = session
        self._url = url

    async def __aenter__(self) -> FakeResponse:
        self._session.inflight += 1
        self._session.max_inflight = max(self._session.max_inflight, self._session.inflight)
        try:
            if self._session.delay:
                await asyncio.sleep(self._session.delay)
            if self._url in self._session.errors:
                left = self._session.fail_counts.get(self._url)
                if left is None:
                    raise self._session.errors[self._url]
                if left > 0:
                    self._session.fail_counts[self._url] = left - 1
                    raise self._session.errors[self._url]
            if self._url not in self._session.mapping:
                raise aiohttp.ClientConnectionError(f"unknown url {self._url}")
            return self._session.mapping[self._url]
        except Exception:
            self._session.inflight -= 1
            raise

    async def __aexit__(self, exc_type, exc, tb) -> None:
        self._session.inflight -= 1
