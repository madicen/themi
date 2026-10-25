import random
from datetime import UTC, datetime

import pytest
from hypothesis import given
from hypothesis import strategies as st

from tests.fakes.scripted_provider import ScriptedProvider
from themi.ai import (
    CallKind,
    Message,
    PermanentError,
    RefusalError,
    RetriesExhausted,
    RetryableError,
    RetryPolicy,
    call_with_retry,
)
from themi.ai.errors import RETRYABLE_STATUSES, error_for_status, parse_retry_after


class FakeSleep:
    def __init__(self) -> None:
        self.waits: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.waits.append(seconds)


@pytest.fixture
def sleep() -> FakeSleep:
    return FakeSleep()


def chat_once(provider: ScriptedProvider):
    return lambda: provider.chat("system", [Message.user("hi")])


# ----- status mapping -------------------------------------------------------


@pytest.mark.parametrize("status", sorted(RETRYABLE_STATUSES))
def test_retryable_statuses(status: int) -> None:
    assert isinstance(error_for_status(status, "x"), RetryableError)


@pytest.mark.parametrize("status", [400, 401, 403, 404, 413, 422, 501])
def test_permanent_statuses(status: int) -> None:
    assert isinstance(error_for_status(status, "x"), PermanentError)


def test_plan_statuses_are_all_retryable() -> None:
    assert {429, 500, 502, 503, 504, 529} <= RETRYABLE_STATUSES


@pytest.mark.parametrize(
    ("header", "seconds"),
    [("7", 7.0), (" 2.5 ", 2.5), ("-3", 0.0), ("", None), (None, None), ("soon", None)],
)
def test_parse_retry_after_seconds(header: str | None, seconds: float | None) -> None:
    assert parse_retry_after(header) == seconds


def test_parse_retry_after_http_date() -> None:
    now = datetime(2026, 10, 21, 16, 0, 0, tzinfo=UTC)
    assert parse_retry_after("Wed, 21 Oct 2026 16:00:30 GMT", now) == 30.0
    assert parse_retry_after("Wed, 21 Oct 2026 15:00:00 GMT", now) == 0.0


# ----- retry behaviour ------------------------------------------------------


async def test_success_needs_no_retry(sleep: FakeSleep) -> None:
    provider = ScriptedProvider().queue_text("hello")
    response = await call_with_retry(chat_once(provider), CallKind.INTERACTIVE, sleep=sleep)
    assert response.text == "hello"
    assert sleep.waits == [] and len(provider.requests) == 1


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504, 529])
async def test_each_retryable_status_is_retried(status: int, sleep: FakeSleep) -> None:
    provider = ScriptedProvider().fail(1, status=status).queue_text("recovered")
    response = await call_with_retry(chat_once(provider), CallKind.INTERACTIVE, sleep=sleep)
    assert response.text == "recovered"
    assert len(provider.requests) == 2 and len(sleep.waits) == 1


@pytest.mark.parametrize("status", [400, 401, 403, 404])
async def test_permanent_errors_are_never_retried(status: int, sleep: FakeSleep) -> None:
    provider = ScriptedProvider().fail(1, status=status).queue_text("unused")
    with pytest.raises(PermanentError) as info:
        await call_with_retry(chat_once(provider), CallKind.BACKGROUND, sleep=sleep)
    assert info.value.status == status
    assert len(provider.requests) == 1 and sleep.waits == []


async def test_refusals_are_not_retried(sleep: FakeSleep) -> None:
    provider = ScriptedProvider().queue_refusal("cyber").queue_text("unused")
    with pytest.raises(RefusalError):
        await call_with_retry(chat_once(provider), CallKind.BACKGROUND, sleep=sleep)
    assert len(provider.requests) == 1


@pytest.mark.parametrize(
    ("kind", "attempts"), [(CallKind.INTERACTIVE, 3), (CallKind.BACKGROUND, 6)]
)
async def test_attempts_are_capped_per_call_kind(
    kind: CallKind, attempts: int, sleep: FakeSleep
) -> None:
    provider = ScriptedProvider().fail(10, status=503)
    with pytest.raises(RetriesExhausted) as info:
        await call_with_retry(chat_once(provider), kind, sleep=sleep)
    assert info.value.attempts == attempts
    assert info.value.last_error.status == 503
    assert len(provider.requests) == attempts
    assert len(sleep.waits) == attempts - 1


async def test_retry_after_wins_over_backoff(sleep: FakeSleep) -> None:
    provider = ScriptedProvider().fail(2, status=429, retry_after=12.0).queue_text("ok")
    await call_with_retry(chat_once(provider), CallKind.INTERACTIVE, sleep=sleep)
    assert sleep.waits == [12.0, 12.0]


async def test_too_long_a_wait_gives_up_for_interactive_calls(sleep: FakeSleep) -> None:
    provider = ScriptedProvider().fail(1, status=429, retry_after=3600).queue_text("ok")
    with pytest.raises(RetriesExhausted) as info:
        await call_with_retry(chat_once(provider), CallKind.INTERACTIVE, sleep=sleep)
    assert info.value.attempts == 1 and sleep.waits == []


async def test_background_calls_accept_longer_waits(sleep: FakeSleep) -> None:
    provider = ScriptedProvider().fail(1, status=429, retry_after=120).queue_text("ok")
    await call_with_retry(chat_once(provider), CallKind.BACKGROUND, sleep=sleep)
    assert sleep.waits == [120]


@pytest.mark.parametrize("exc", [TimeoutError("read timed out"), ConnectionError("reset")])
async def test_bare_timeouts_and_connection_errors_are_retried(
    exc: Exception, sleep: FakeSleep
) -> None:
    provider = ScriptedProvider().queue_error(exc).queue_text("ok")
    response = await call_with_retry(chat_once(provider), CallKind.INTERACTIVE, sleep=sleep)
    assert response.text == "ok"


async def test_other_exceptions_propagate_untouched(sleep: FakeSleep) -> None:
    provider = ScriptedProvider().queue_error(KeyError("bug"))
    with pytest.raises(KeyError):
        await call_with_retry(chat_once(provider), CallKind.BACKGROUND, sleep=sleep)


async def test_on_retry_hook_sees_each_retry(sleep: FakeSleep) -> None:
    seen: list[tuple[int, int | None]] = []

    async def hook(attempt: int, error: RetryableError, wait: float) -> None:
        seen.append((attempt, error.status))

    provider = ScriptedProvider().fail(1, status=503).fail(1, status=529).queue_text("ok")
    await call_with_retry(chat_once(provider), CallKind.INTERACTIVE, sleep=sleep, on_retry=hook)
    assert seen == [(1, 503), (2, 529)]

    sync_seen: list[int] = []
    provider = ScriptedProvider().fail(1).queue_text("ok")
    await call_with_retry(
        chat_once(provider),
        CallKind.INTERACTIVE,
        sleep=sleep,
        on_retry=lambda attempt, error, wait: sync_seen.append(attempt),
    )
    assert sync_seen == [1]


async def test_backoff_uses_the_injected_rng(sleep: FakeSleep) -> None:
    provider = ScriptedProvider().fail(3, status=503).queue_text("ok")
    await call_with_retry(
        chat_once(provider), CallKind.BACKGROUND, sleep=sleep, rng=random.Random(42)
    )
    expected_rng = random.Random(42)
    expected = [expected_rng.uniform(0, min(60, 2**i)) for i in range(3)]
    assert sleep.waits == expected


@given(retry=st.integers(min_value=0, max_value=40), seed=st.integers())
def test_backoff_always_stays_within_full_jitter_bounds(retry: int, seed: int) -> None:
    policy = RetryPolicy()
    delay = policy.backoff(retry, random.Random(seed))
    assert 0.0 <= delay <= min(policy.cap, policy.base * 2**retry)
    assert delay <= 60.0
