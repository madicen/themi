"""Errors every adapter maps its SDK's exceptions onto.

The retry policy only needs to know which kind it got:
- `RetryableError`: overloaded, rate-limited, timed out, or the connection dropped.
- `PermanentError`: configuration or request problems (bad key, unknown model).
- `RefusalError`: the model declined; repeating the same request won't help.
- `CapabilityError`: this provider can't do what was asked (e.g. no audio input).
"""

from __future__ import annotations

from datetime import datetime
from email.utils import parsedate_to_datetime

from themi import clock

# Overloaded (529), rate-limited (429), server trouble (5xx) and request timeout (408).
RETRYABLE_STATUSES = frozenset({408, 429, 500, 502, 503, 504, 529})


class AIError(Exception):
    pass


class RetryableError(AIError):
    def __init__(
        self, message: str, *, status: int | None = None, retry_after: float | None = None
    ) -> None:
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


class PermanentError(AIError):
    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class RefusalError(AIError):
    def __init__(self, message: str = "the model declined", *, category: str | None = None):
        super().__init__(message)
        self.category = category


class CapabilityError(AIError):
    pass


class MalformedOutputError(AIError):
    """The model answered, but not in the shape asked for (bad JSON, truncated output)."""


class RetriesExhausted(AIError):
    """Raised by the retry policy when it gives up; `last_error` says why."""

    def __init__(self, attempts: int, last_error: RetryableError) -> None:
        super().__init__(f"gave up after {attempts} attempt(s): {last_error}")
        self.attempts = attempts
        self.last_error = last_error


def error_for_status(
    status: int, message: str, retry_after: float | None = None
) -> RetryableError | PermanentError:
    if status in RETRYABLE_STATUSES:
        return RetryableError(message, status=status, retry_after=retry_after)
    return PermanentError(message, status=status)


def parse_retry_after(value: str | None, now: datetime | None = None) -> float | None:
    """Seconds to wait from a `Retry-After` header (delta-seconds or an HTTP date)."""
    if value is None or not value.strip():
        return None
    value = value.strip()
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, (when - (now or clock.now())).total_seconds())
