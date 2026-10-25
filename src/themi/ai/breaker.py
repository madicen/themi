"""Circuit breakers, one per (member, backend).

After 5 consecutive failed attempts a backend is skipped for 5 minutes, then
probed with a single request: success closes it, failure opens it for
another 5 minutes. State lives in memory; a restart starts every breaker
closed, which is the safe direction.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from themi import clock

FAILURE_THRESHOLD = 5
COOL_DOWN = timedelta(minutes=5)


class BreakerState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class _Breaker:
    failures: int = 0
    opened_at: datetime | None = None
    probing: bool = False


class BreakerBoard:
    def __init__(self, threshold: int = FAILURE_THRESHOLD, cool_down: timedelta = COOL_DOWN):
        self.threshold = threshold
        self.cool_down = cool_down
        self._breakers: dict[tuple[int, int], _Breaker] = {}

    def _get(self, key: tuple[int, int]) -> _Breaker:
        return self._breakers.setdefault(key, _Breaker())

    def state(self, member_id: int, backend_id: int) -> BreakerState:
        breaker = self._get((member_id, backend_id))
        if breaker.opened_at is None:
            return BreakerState.CLOSED
        if clock.now() - breaker.opened_at >= self.cool_down:
            return BreakerState.HALF_OPEN
        return BreakerState.OPEN

    def allow(self, member_id: int, backend_id: int) -> bool:
        """May a request go to this backend now? Claims the probe when half-open."""
        state = self.state(member_id, backend_id)
        if state is BreakerState.CLOSED:
            return True
        if state is BreakerState.OPEN:
            return False
        breaker = self._get((member_id, backend_id))
        if breaker.probing:
            return False  # someone else's probe is in flight
        breaker.probing = True
        return True

    def record_success(self, member_id: int, backend_id: int) -> None:
        self._breakers[(member_id, backend_id)] = _Breaker()

    def record_failure(self, member_id: int, backend_id: int) -> None:
        breaker = self._get((member_id, backend_id))
        if breaker.probing or breaker.opened_at is not None:
            # A failed probe re-opens for a fresh cool-down.
            breaker.opened_at = clock.now()
            breaker.probing = False
            return
        breaker.failures += 1
        if breaker.failures >= self.threshold:
            breaker.opened_at = clock.now()

    def release_probe(self, member_id: int, backend_id: int) -> None:
        """A probe ended without a verdict (e.g. a permanent error); let another try."""
        self._get((member_id, backend_id)).probing = False
