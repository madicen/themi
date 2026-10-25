"""Periodic jobs and a durable queue of background work.

Periodic jobs ("flush the outbox every 30 seconds") live in memory and are
registered at startup. Queued jobs ("triage this email") live in the
`job_queue` table, so they survive restarts.

Every job runs isolated: an exception is logged and never stops the others.
A queued job that raises `Deferred` (no AI backend could take it right now)
goes back in the queue for later and is never dropped; other failures back
off and give up after `MAX_ATTEMPTS`.

Time comes from `themi.clock`, so tests tick the scheduler by hand with
`run_due()` instead of waiting.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from themi import clock
from themi.ai.router import Deferred
from themi.localtime import to_utc_iso
from themi.storage.db import Database

log = logging.getLogger(__name__)

PeriodicFn = Callable[[], Awaitable[Any]]
JobHandler = Callable[[dict[str, Any]], Awaitable[Any]]

MAX_ATTEMPTS = 8
FAILURE_BACKOFF = (
    timedelta(minutes=1),
    timedelta(minutes=5),
    timedelta(minutes=30),
    timedelta(hours=2),
)
DEFER_BACKOFF = timedelta(minutes=5)  # when a Deferred carries no retry hint


@dataclass
class PeriodicJob:
    name: str
    every: timedelta
    fn: PeriodicFn
    jitter: timedelta
    next_run: datetime


@dataclass
class TickReport:
    periodic: list[str] = field(default_factory=list)
    queued: list[int] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)


class Scheduler:
    def __init__(self, db: Database, *, rng: random.Random | None = None) -> None:
        self.db = db
        self._rng = rng or random.Random()
        self._periodic: dict[str, PeriodicJob] = {}
        self._handlers: dict[str, JobHandler] = {}
        self._recover_interrupted()

    # ----- registration -------------------------------------------------------

    def every(
        self,
        name: str,
        interval: timedelta,
        fn: PeriodicFn,
        *,
        jitter: timedelta = timedelta(0),
        first_run: datetime | None = None,
    ) -> None:
        if name in self._periodic:
            raise ValueError(f"periodic job {name} is already registered")
        self._periodic[name] = PeriodicJob(name, interval, fn, jitter, first_run or clock.now())

    def handler(self, kind: str) -> Callable[[JobHandler], JobHandler]:
        def register(fn: JobHandler) -> JobHandler:
            if kind in self._handlers:
                raise ValueError(f"a handler for {kind} jobs is already registered")
            self._handlers[kind] = fn
            return fn

        return register

    def enqueue(
        self,
        kind: str,
        payload: dict[str, Any] | None = None,
        *,
        run_after: datetime | None = None,
        dedupe_key: str | None = None,
    ) -> int | None:
        """Queue background work. Returns its id, or None if an identical job is pending."""
        now = to_utc_iso(clock.now())
        if dedupe_key and self.db.one(
            "SELECT 1 FROM job_queue WHERE dedupe_key = ? AND status IN ('queued', 'running')",
            (dedupe_key,),
        ):
            return None
        return self.db.execute(
            "INSERT INTO job_queue (kind, payload, run_after, dedupe_key, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                kind,
                json.dumps(payload or {}),
                to_utc_iso(run_after or clock.now()),
                dedupe_key,
                now,
                now,
            ),
        )

    # ----- running ------------------------------------------------------------

    async def run_due(self) -> TickReport:
        report = TickReport()
        now = clock.now()
        for job in list(self._periodic.values()):
            if job.next_run > now:
                continue
            job.next_run = now + job.every + self._jitter(job.jitter)
            report.periodic.append(job.name)
            try:
                await job.fn()
            except Exception:
                log.exception("Periodic job %s failed", job.name)
                report.failures.append(job.name)
        for row in self._due_jobs(now):
            report.queued.append(row["id"])
            if not await self._run_queued(row):
                report.failures.append(f"{row['kind']}#{row['id']}")
        return report

    async def run_forever(
        self, stop: asyncio.Event, tick: timedelta = timedelta(seconds=15)
    ) -> None:
        """Tick until `stop` is set. A job in progress always finishes first."""
        while not stop.is_set():
            await self.run_due()
            with suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=tick.total_seconds())

    def _due_jobs(self, now: datetime) -> list[dict[str, Any]]:
        return self.db.query(
            "SELECT * FROM job_queue WHERE status = 'queued' AND run_after <= ? "
            "ORDER BY run_after, id",
            (to_utc_iso(now),),
        )

    async def _run_queued(self, row: dict[str, Any]) -> bool:
        handler = self._handlers.get(row["kind"])
        if handler is None:
            log.warning("No handler for %s jobs; job %s stays queued", row["kind"], row["id"])
            self._reschedule(row["id"], clock.now() + DEFER_BACKOFF, error="no handler")
            return False
        self._set_status(row["id"], "running")
        try:
            await handler(json.loads(row["payload"]))
        except Deferred as exc:
            wait = timedelta(seconds=exc.retry_after) if exc.retry_after else DEFER_BACKOFF
            log.info("Job %s (%s) deferred for %s", row["id"], row["kind"], wait)
            self.db.execute(
                "UPDATE job_queue SET status = 'queued', run_after = ?, deferrals = deferrals + 1,"
                " last_error = 'Deferred', updated_at = ? WHERE id = ?",
                (to_utc_iso(clock.now() + wait), to_utc_iso(clock.now()), row["id"]),
            )
            return True
        except Exception as exc:
            attempts = row["attempts"] + 1
            if attempts >= MAX_ATTEMPTS:
                log.error(
                    "Job %s (%s) failed %d times; giving up",
                    row["id"],
                    row["kind"],
                    attempts,
                    exc_info=True,
                )
                self.db.execute(
                    "UPDATE job_queue SET status = 'failed', attempts = ?, last_error = ?, "
                    "updated_at = ? WHERE id = ?",
                    (attempts, type(exc).__name__, to_utc_iso(clock.now()), row["id"]),
                )
            else:
                log.warning(
                    "Job %s (%s) failed (%s); retrying later",
                    row["id"],
                    row["kind"],
                    type(exc).__name__,
                    exc_info=True,
                )
                backoff = FAILURE_BACKOFF[min(attempts - 1, len(FAILURE_BACKOFF) - 1)]
                self.db.execute(
                    "UPDATE job_queue SET status = 'queued', attempts = ?, last_error = ?, "
                    "run_after = ?, updated_at = ? WHERE id = ?",
                    (
                        attempts,
                        type(exc).__name__,
                        to_utc_iso(clock.now() + backoff),
                        to_utc_iso(clock.now()),
                        row["id"],
                    ),
                )
            return False
        self._set_status(row["id"], "done")
        return True

    # ----- helpers ------------------------------------------------------------

    def _jitter(self, jitter: timedelta) -> timedelta:
        if jitter <= timedelta(0):
            return timedelta(0)
        return timedelta(seconds=self._rng.uniform(0, jitter.total_seconds()))

    def _set_status(self, job_id: int, status: str) -> None:
        self.db.execute(
            "UPDATE job_queue SET status = ?, updated_at = ? WHERE id = ?",
            (status, to_utc_iso(clock.now()), job_id),
        )

    def _reschedule(self, job_id: int, when: datetime, *, error: str) -> None:
        self.db.execute(
            "UPDATE job_queue SET run_after = ?, last_error = ?, updated_at = ? WHERE id = ?",
            (to_utc_iso(when), error, to_utc_iso(clock.now()), job_id),
        )

    def _recover_interrupted(self) -> None:
        """Jobs left 'running' by a crash or kill go back in the queue."""
        interrupted = self.db.scalar("SELECT COUNT(*) FROM job_queue WHERE status = 'running'")
        if interrupted:
            self.db.execute(
                "UPDATE job_queue SET status = 'queued', updated_at = ? WHERE status = 'running'",
                (to_utc_iso(clock.now()),),
            )
            log.info("Re-queued %d job(s) interrupted by the last shutdown", interrupted)

    def jobs(self, status: str | None = None) -> list[dict[str, Any]]:
        if status is None:
            return self.db.query("SELECT * FROM job_queue ORDER BY id")
        return self.db.query("SELECT * FROM job_queue WHERE status = ? ORDER BY id", (status,))
