from __future__ import annotations

import time
from collections import defaultdict

CLOSED = "closed"
OPEN = "open"
HALF_OPEN = "half_open"


class CircuitBreaker:
    """Block a domain after many recent errors; allow it again after a pause."""

    def __init__(
        self,
        failure_threshold: int = 5,
        failure_window: float = 60.0,
        recovery_timeout: float = 30.0,
    ) -> None:
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be >= 1")
        if failure_window <= 0 or recovery_timeout <= 0:
            raise ValueError("failure_window and recovery_timeout must be > 0")
        self.failure_threshold = failure_threshold
        self.failure_window = failure_window
        self.recovery_timeout = recovery_timeout
        self._state: dict[str, str] = defaultdict(lambda: CLOSED)
        self._failures: dict[str, list[float]] = defaultdict(list)
        self._opened_at: dict[str, float] = {}

    def state(self, domain: str) -> str:
        return self._state[domain]

    def _prune(self, domain: str, now: float) -> None:
        window_start = now - self.failure_window
        self._failures[domain] = [
            t for t in self._failures[domain] if t >= window_start
        ]

    def allow(self, domain: str) -> bool:
        """True = you may send a request to this domain."""
        now = time.monotonic()
        state = self._state[domain]
        if state == CLOSED:
            return True
        if state == OPEN:
            if now - self._opened_at[domain] < self.recovery_timeout:
                return False
            self._state[domain] = HALF_OPEN
            return True
        # half_open: only the probe that just passed OPEN is in flight
        return False

    def record_success(self, domain: str) -> None:
        self._failures[domain].clear()
        self._state[domain] = CLOSED
        self._opened_at.pop(domain, None)

    def record_failure(self, domain: str) -> None:
        now = time.monotonic()
        if self._state[domain] == HALF_OPEN:
            self._state[domain] = OPEN
            self._opened_at[domain] = now
            return
        self._failures[domain].append(now)
        self._prune(domain, now)
        if len(self._failures[domain]) >= self.failure_threshold:
            self._state[domain] = OPEN
            self._opened_at[domain] = now