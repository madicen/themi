"""One retry policy for every provider.

- Retried: `RetryableError` (429, 5xx, 529, timeouts, dropped connections), plus
  bare `TimeoutError` / `ConnectionError` that slip through an adapter.
- Never retried: `PermanentError`, `RefusalError`, `CapabilityError`.
- Delay: full jitter, `uniform(0, min(cap, base * 2**retry))`. A provider's
  `Retry-After` wins over the computed delay.
- Attempts: 3 when someone is waiting (interactive), 6 for background work.
- If `Retry-After` asks for longer than the call kind can wait (say a quota
  reset an hour away), give up now so the fallback chain can take over.

`sleep` and `rng` are injectable, so tests run instantly and deterministically.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from themi.ai.errors import RetriesExhausted, RetryableError
from themi.ai.types import CallKind

Sleep = Callable[[float], Awaitable[None]]
OnRetry = Callable[[int, RetryableError, float], Awaitable[None] | None]

log = logging.getLogger(__name__)


def _frozen(d: dict[CallKind, int | float]) -> Mapping[CallKind, int | float]:
    return MappingProxyType(d)


@dataclass(frozen=True)
class RetryPolicy:
    base: float = 1.0
    cap: float = 60.0
    attempts: Mapping[CallKind, int | float] = field(
        default_factory=lambda: _frozen({CallKind.INTERACTIVE: 3, CallKind.BACKGROUND: 6})
    )
    # The longest single wait each kind will accept (from Retry-After or backoff).
    max_wait: Mapping[CallKind, int | float] = field(
        default_factory=lambda: _frozen({CallKind.INTERACTIVE: 20.0, CallKind.BACKGROUND: 300.0})
    )

    def attempts_for(self, kind: CallKind) -> int:
        return int(self.attempts[kind])

    def backoff(self, retry: int, rng: random.Random) -> float:
        """Delay before retry number `retry` (0 = the first retry)."""
        return rng.uniform(0.0, min(self.cap, self.base * 2**retry))

    def delay(self, retry: int, error: RetryableError, rng: random.Random) -> float:
        if error.retry_after is not None:
            return error.retry_after
        return self.backoff(retry, rng)


DEFAULT_POLICY = RetryPolicy()


def _as_retryable(exc: BaseException) -> RetryableError | None:
    if isinstance(exc, RetryableError):
        return exc
    if isinstance(exc, TimeoutError | ConnectionError):
        return RetryableError(f"{type(exc).__name__}: {exc}")
    return None


async def call_with_retry[T](
    fn: Callable[[], Awaitable[T]],
    kind: CallKind,
    *,
    policy: RetryPolicy = DEFAULT_POLICY,
    sleep: Sleep = asyncio.sleep,
    rng: random.Random | None = None,
    on_retry: OnRetry | None = None,
) -> T:
    """Run `fn`, retrying transient failures per `policy`.

    Raises `RetriesExhausted` once attempts run out (or a wait would be too
    long); any non-retryable error propagates immediately.
    """
    rng = rng or random.Random()
    attempts = policy.attempts_for(kind)
    for attempt in range(attempts):
        try:
            return await fn()
        except Exception as exc:
            error = _as_retryable(exc)
            if error is None:
                raise
            if attempt == attempts - 1:
                raise RetriesExhausted(attempt + 1, error) from exc
            wait = policy.delay(attempt, error, rng)
            if wait > policy.max_wait[kind]:
                log.info("not waiting %.0fs for a %s call; giving up", wait, kind.value)
                raise RetriesExhausted(attempt + 1, error) from exc
            log.info(
                "AI call failed (%s), retry %d/%d in %.1fs",
                error.status or type(exc).__name__,
                attempt + 1,
                attempts - 1,
                wait,
            )
            if on_retry is not None:
                result = on_retry(attempt + 1, error, wait)
                if result is not None:
                    await result
            await sleep(wait)
    raise AssertionError("unreachable")  # pragma: no cover
