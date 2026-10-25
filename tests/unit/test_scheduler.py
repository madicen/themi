import random
from datetime import datetime, timedelta

import pytest

from themi import clock
from themi.ai.router import Deferred
from themi.scheduler import FAILURE_BACKOFF, MAX_ATTEMPTS, Scheduler
from themi.storage import open_database
from themi.storage.db import Database


@pytest.fixture
def db() -> Database:
    return open_database(":memory:")


@pytest.fixture
def scheduler(db: Database) -> Scheduler:
    return Scheduler(db, rng=random.Random(7))


def deferred(retry_after: float | None = None) -> Deferred:
    from themi.ai.errors import RetriesExhausted, RetryableError

    errors: list[tuple[str, Exception]] = []
    if retry_after is not None:
        errors.append(
            ("Gemini", RetriesExhausted(1, RetryableError("429", retry_after=retry_after)))
        )
    return Deferred("no AI backend could handle email_triage", errors)


# ----- periodic jobs ----------------------------------------------------------


async def test_periodic_jobs_run_when_due(scheduler: Scheduler, frozen_clock: datetime) -> None:
    runs: list[datetime] = []

    async def flush() -> None:
        runs.append(clock.now())

    scheduler.every("outbox.flush", timedelta(seconds=30), flush)
    assert (await scheduler.run_due()).periodic == ["outbox.flush"]
    assert (await scheduler.run_due()).periodic == []  # not due again yet
    clock.advance(timedelta(seconds=30))
    await scheduler.run_due()
    assert runs == [frozen_clock, frozen_clock + timedelta(seconds=30)]


async def test_a_failing_job_does_not_stop_the_others(
    scheduler: Scheduler, frozen_clock: datetime
) -> None:
    ran: list[str] = []

    async def broken() -> None:
        raise RuntimeError("boom")

    async def fine() -> None:
        ran.append("fine")

    scheduler.every("broken", timedelta(minutes=1), broken)
    scheduler.every("fine", timedelta(minutes=1), fine)
    report = await scheduler.run_due()
    assert report.failures == ["broken"] and ran == ["fine"]
    clock.advance(timedelta(minutes=1))
    assert (await scheduler.run_due()).periodic == ["broken", "fine"]  # still scheduled


async def test_jitter_spreads_runs_within_bounds(
    scheduler: Scheduler, frozen_clock: datetime
) -> None:
    async def noop() -> None:
        return None

    scheduler.every("job", timedelta(minutes=10), noop, jitter=timedelta(minutes=2))
    await scheduler.run_due()
    next_run = scheduler._periodic["job"].next_run
    assert frozen_clock + timedelta(minutes=10) <= next_run <= frozen_clock + timedelta(minutes=12)


def test_duplicate_registrations_are_refused(scheduler: Scheduler) -> None:
    async def noop(*_) -> None:
        return None

    scheduler.every("a", timedelta(minutes=1), noop)
    with pytest.raises(ValueError):
        scheduler.every("a", timedelta(minutes=1), noop)
    scheduler.handler("triage")(noop)
    with pytest.raises(ValueError):
        scheduler.handler("triage")(noop)


# ----- the durable queue ------------------------------------------------------


async def test_queued_jobs_run_once_when_due(scheduler: Scheduler, frozen_clock: datetime) -> None:
    seen: list[dict] = []

    @scheduler.handler("triage")
    async def triage(payload: dict) -> None:
        seen.append(payload)

    scheduler.enqueue("triage", {"message": "m1"})
    later = scheduler.enqueue(
        "triage", {"message": "m2"}, run_after=frozen_clock + timedelta(hours=1)
    )
    await scheduler.run_due()
    await scheduler.run_due()
    assert seen == [{"message": "m1"}]
    clock.advance(timedelta(hours=1))
    await scheduler.run_due()
    assert seen[-1] == {"message": "m2"}
    assert [j["status"] for j in scheduler.jobs()] == ["done", "done"]
    assert later is not None


async def test_deferred_work_is_requeued_and_never_dropped(
    scheduler: Scheduler, frozen_clock: datetime
) -> None:
    calls = 0

    @scheduler.handler("triage")
    async def triage(payload: dict) -> None:
        nonlocal calls
        calls += 1
        if calls <= 20:
            raise deferred()

    scheduler.enqueue("triage", {})
    for _ in range(20):
        await scheduler.run_due()
        clock.advance(timedelta(minutes=5))
    (job,) = scheduler.jobs()
    assert job["status"] == "queued" and job["deferrals"] == 20 and job["attempts"] == 0
    await scheduler.run_due()
    assert scheduler.jobs()[0]["status"] == "done"


async def test_deferral_honours_the_provider_retry_hint(
    scheduler: Scheduler, frozen_clock: datetime
) -> None:
    @scheduler.handler("triage")
    async def triage(payload: dict) -> None:
        raise deferred(retry_after=3600)

    scheduler.enqueue("triage", {})
    await scheduler.run_due()
    (job,) = scheduler.jobs()
    assert datetime.fromisoformat(job["run_after"]) == frozen_clock + timedelta(hours=1)


async def test_other_failures_back_off_then_give_up(
    scheduler: Scheduler, frozen_clock: datetime
) -> None:
    @scheduler.handler("broken")
    async def broken(payload: dict) -> None:
        raise ValueError("bad data")

    scheduler.enqueue("broken", {})
    await scheduler.run_due()
    (job,) = scheduler.jobs()
    assert job["attempts"] == 1 and job["last_error"] == "ValueError"
    assert datetime.fromisoformat(job["run_after"]) == frozen_clock + FAILURE_BACKOFF[0]
    for _ in range(MAX_ATTEMPTS):
        clock.advance(timedelta(hours=3))
        await scheduler.run_due()
    assert scheduler.jobs()[0]["status"] == "failed"
    assert scheduler.jobs()[0]["attempts"] == MAX_ATTEMPTS


async def test_jobs_without_a_handler_wait(scheduler: Scheduler, frozen_clock: datetime) -> None:
    scheduler.enqueue("future_feature", {})
    report = await scheduler.run_due()
    assert report.failures and scheduler.jobs()[0]["status"] == "queued"


def test_dedupe_keys_keep_one_pending_copy(scheduler: Scheduler) -> None:
    assert scheduler.enqueue("triage", {}, dedupe_key="email:abc") is not None
    assert scheduler.enqueue("triage", {}, dedupe_key="email:abc") is None
    assert len(scheduler.jobs()) == 1


def test_jobs_interrupted_by_a_crash_are_requeued(db: Database) -> None:
    scheduler = Scheduler(db)
    job_id = scheduler.enqueue("triage", {})
    db.execute("UPDATE job_queue SET status = 'running' WHERE id = ?", (job_id,))
    restarted = Scheduler(db)
    assert restarted.jobs()[0]["status"] == "queued"
