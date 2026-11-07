"""The laundry (31): a finished wash gets moved to the dryer, or rescued before it sours.

From the washer and dryer's events (LG ThinQ, 30):

- The washer finishing (or seen running, then off) makes a wet load (`laundry_loads`) and an
  effort-1 hands-on task, for whoever has the most room right now. Its nudge waits half an
  hour (the load's often moved by then), then asks "Into the dryer now, or later?"; Later
  asks again in an hour. The family's daily message limit doesn't hold it back.
- The dryer starting means the wet load is in it: the task is done, and a nudge not yet
  sent is taken back.
- The washer starting again supersedes the wet load (moved out, or washed again); its task
  goes quietly, and the new wash makes a new load when it finishes.
- Past the family's freshness hours (default 8; `laundry.fresh`, every 15 minutes) the
  task becomes "Rewash the washer load", timed so the rewash finishes as that person's
  next good window begins. The message names both times, and goes out in the half hour
  before the start (a rewash for the morning isn't suggested at night).

Washer and dryer runs are kept as cycles (`appliance_cycles`), like the dishwasher's.
Nothing here changes anything outside Themi: the task and its nudges are Themi's own.
"""

from __future__ import annotations

import logging
import secrets
from datetime import date, datetime, timedelta
from typing import Any, ClassVar
from zoneinfo import ZoneInfo

from pydantic import field_validator

from themi import clock
from themi.accounts import Member
from themi.accounts.household import HouseholdSettings
from themi.channels.outbox import Button, Priority
from themi.connectors.thinq import FINISHED, IDLE, RUNNING, ApplianceEvent, ThinqWatcher
from themi.core import keys
from themi.core.services import Services
from themi.core.tasks import Task, TaskBoard, TaskChange, clock_words
from themi.energy.windows import STEP, Projection, next_window
from themi.localtime import to_utc_iso

log = logging.getLogger(__name__)

KIND = "laundry"  # the outbox kind: "/pause laundry" holds these
TITLE = "Move the wet load to the dryer"
RESCUE_TITLE = "Rewash the washer load"
WASHED_TEXT = "The washer finished at {at}. Into the dryer now, or later?"
RESCUE_TEXT = (
    "The washer load has been sitting since {at}, so it'll want a rewash: started around "
    "{start}, it'd be done about {ready}. Rewash it, or leave it for now?"
)
SUPERSEDED_TEXT = "The washer's running again, so nothing to move for now."
MOVED, LATER, REWASHED = "Moved it", "Later", "Rewash started"
MOVE_AFTER = timedelta(minutes=30)  # the first nudge waits this long after the wash ends
LATER_FOR = 60  # minutes: Later on a laundry nudge asks again in an hour
RESCUE_LEAD = timedelta(minutes=30)  # a rewash suggestion goes out at most this long before


class LaundrySettings(HouseholdSettings):
    """CR7c: how long a wet load stays fresh, and how long a rewash takes (31). The thinq
    module's."""

    module: ClassVar[str] = "thinq"
    laundry_fresh_hours: float = 8.0
    laundry_rinse_minutes: int = 30

    @field_validator("laundry_fresh_hours")
    @classmethod
    def _fresh(cls, value: float) -> float:
        if not 1 <= value <= 48:
            raise ValueError("a wet load stays fresh for 1 to 48 hours")
        return value

    @field_validator("laundry_rinse_minutes")
    @classmethod
    def _rinse(cls, value: int) -> int:
        if not 5 <= value <= 180:
            raise ValueError("a rewash takes 5 to 180 minutes")
        return value


class Laundry:
    def __init__(self, services: Services, board: TaskBoard, watcher: ThinqWatcher) -> None:
        self.services = services
        self.board = board
        self.watcher = watcher
        self.store = services.store
        self.db = services.store.db

    def install(self) -> None:
        self.services.provide(keys.laundry, self)
        self.watcher.listeners.append(self.on_event)
        self.board.own_nudges.append(self._nudge)
        self.board.change_listeners.append(self._task_changed)

    # ----- the appliances -------------------------------------------------------------

    async def on_event(self, event: ApplianceEvent) -> None:
        if event.appliance not in ("washer", "dryer"):
            return
        # Read every few minutes, a washer can finish and power off between reads: running,
        # then off, is a finished wash all the same.
        was_running = self._running(event.device_id) is not None
        self._cycle(event)
        if event.appliance == "washer" and event.state == RUNNING:
            for load in self._wet(washer=event.device_id):
                await self._supersede(load)
        elif event.appliance == "washer" and (
            event.state == FINISHED or (event.state == IDLE and was_running)
        ):
            await self._washed(event)
        elif event.appliance == "dryer" and event.state == RUNNING:
            for load in self._wet():
                await self._dried(load)

    def _cycle(self, event: ApplianceEvent) -> None:
        at = to_utc_iso(event.at)
        running = self._running(event.device_id)
        if event.state == RUNNING and running is None:
            self.db.execute(
                "INSERT INTO appliance_cycles (device_id, started_at) VALUES (?, ?)",
                (event.device_id, at),
            )
        elif event.state != RUNNING and running is not None:
            self.db.execute(
                "UPDATE appliance_cycles SET ended_at = ? WHERE id = ?", (at, running["id"])
            )

    def _running(self, device_id: int) -> dict[str, Any] | None:
        return self.db.one(
            "SELECT id FROM appliance_cycles WHERE device_id = ? AND ended_at IS NULL",
            (device_id,),
        )

    async def _washed(self, event: ApplianceEvent) -> None:
        assignment = self.board.matcher.roomiest("physical", 1, event.at)
        load_id = self.db.execute(
            "INSERT INTO laundry_loads (washer_id, finished_at, status) VALUES (?, ?, 'wet')",
            (event.device_id, to_utc_iso(event.at)),
        )
        task = await self.board.create(
            assignment.assignee,
            TITLE,
            "physical",
            1,
            nudge=False,
            off_wall=True,  # it comes and goes with the washer; the wall's lists stay calm
            assignment=assignment,
        )
        self.db.execute("UPDATE laundry_loads SET task_id = ? WHERE id = ?", (task.id, load_id))
        await self.board.prompt(task)  # now it's known as the load's: its own nudge

    async def _dried(self, load: dict[str, Any]) -> None:
        self._close(load, "dried")
        task = self._task(load)
        if task is not None and task.assignee is not None:
            await self.board.complete(task.id, self.store.get_member(task.assignee))

    async def _supersede(self, load: dict[str, Any]) -> None:
        self._close(load, "superseded")
        task = self._task(load)
        if task is None:
            return
        await self._settle_sent(task, SUPERSEDED_TEXT)
        await self.board.cancel(task.id, self._admin())

    # ----- the freshness check ----------------------------------------------------------

    async def check_fresh(self) -> int:
        """Scheduler job: a wet load past the fresh hours is offered a rewash, once.
        Returns how many."""
        hours = self.store.household(LaundrySettings).laundry_fresh_hours  # CR7c
        cutoff = to_utc_iso(clock.now() - timedelta(hours=hours))
        rows = self.db.query(
            "SELECT * FROM laundry_loads WHERE status = 'wet' AND rescue_at IS NULL "
            "AND finished_at <= ?",
            (cutoff,),
        )
        for load in rows:
            self.db.execute(
                "UPDATE laundry_loads SET rescue_at = ? WHERE id = ?",
                (to_utc_iso(clock.now()), load["id"]),
            )
            task = self._task(load)
            if task is None or task.assignee is None:
                continue
            member = self.store.get_member(task.assignee)
            task = await self.board.update(task.id, member, title=RESCUE_TITLE)
            # Put off ("Later"), it waits: the rewash is what comes back when that runs out.
            if task.status == "open":
                await self.board.prompt(task)
        return len(rows)

    def rinse_times(self, member: Member, now: datetime) -> tuple[datetime, datetime]:
        """(start, finish) for a rewash that finishes as their next good window begins. When
        that start falls in quiet hours or a busy time, where no message can reach them, it
        starts as soon as one can and finishes that much into the window."""
        rinse = timedelta(minutes=self.store.household(LaundrySettings).laundry_rinse_minutes)
        model = self.board.matcher.model
        ready = next_window(model, member, now + rinse)
        start = ready - rinse
        projection = Projection(model, member, start)
        while projection.quiet(start) and start < ready:
            start += STEP
        return start, start + rinse

    # ----- the nudge ------------------------------------------------------------------

    async def _nudge(
        self, task: Task, member: Member, not_before: datetime | None, deadline: datetime | None
    ) -> bool:
        load = self.db.one("SELECT * FROM laundry_loads WHERE task_id = ?", (task.id,))
        if load is None:
            return False
        if load["status"] != "wet":
            return True  # already handled; nothing to ask
        tz, now = self._tz(), clock.now()
        finished = datetime.fromisoformat(load["finished_at"]).astimezone(tz)
        if load["rescue_at"] is None:
            text = WASHED_TEXT.format(at=self._when(finished, now.astimezone(tz).date()))
            done = MOVED
            # Time-bound: due when it may go, so the daily limit doesn't hold it to morning.
            # Quiet hours, busy times and a pause still do.
            not_before = max(now, finished + MOVE_AFTER, not_before or now)
            deadline = not_before
        else:
            start, ready = self.rinse_times(member, max(now, not_before or now))
            self.db.execute(
                "UPDATE laundry_loads SET rinse_from = ?, ready_at = ? WHERE id = ?",
                (to_utc_iso(start), to_utc_iso(ready), load["id"]),
            )
            # It goes out shortly before the start, never after, so it's read on the
            # start's day: "today" and "yesterday" are counted from there.
            day = start.astimezone(tz).date()
            text = RESCUE_TEXT.format(
                at=self._when(finished, day),
                start=self._when(start.astimezone(tz), day),
                ready=self._when(ready.astimezone(tz), day),
            )
            done = REWASHED
            not_before = max(now, start - RESCUE_LEAD)
            deadline = min(deadline or start, start)
        self.board.withdraw_prompt(task)  # one nudge per load waiting for them
        result = await self.services.outbox.send(
            member,
            text,
            priority=Priority.NORMAL,
            kind=KIND,
            buttons=[
                Button(done, "task", {"task": task.id, "action": "done"}),
                Button(LATER, "task", {"task": task.id, "action": "later", "minutes": LATER_FOR}),
            ],
            not_before=not_before,
            deadline=deadline,
            dedupe_key=f"task-{task.id}-{secrets.token_hex(4)}",  # one of the task's nudges
        )
        if result.outbox_id is not None:
            self.db.execute(
                "UPDATE tasks SET prompt_outbox_id = ? WHERE id = ?", (result.outbox_id, task.id)
            )
        return True

    async def _task_changed(self, task: Task, change: TaskChange, interactive: bool) -> None:
        """Done or taken off the list some other way (a tap, a word in chat): the load is
        handled, as far as Themi's concerned."""
        if change not in ("done", "cancelled"):
            return
        load = self.db.one(
            "SELECT * FROM laundry_loads WHERE task_id = ? AND status = 'wet'", (task.id,)
        )
        if load is not None:
            self._close(load, "done")

    # ----- small things -------------------------------------------------------------------

    def _wet(self, washer: int | None = None) -> list[dict[str, Any]]:
        if washer is None:
            return self.db.query("SELECT * FROM laundry_loads WHERE status = 'wet' ORDER BY id")
        return self.db.query(
            "SELECT * FROM laundry_loads WHERE status = 'wet' AND washer_id = ? ORDER BY id",
            (washer,),
        )

    def _close(self, load: dict[str, Any], status: str) -> None:
        self.db.execute(
            "UPDATE laundry_loads SET status = ?, closed_at = ? WHERE id = ? AND status = 'wet'",
            (status, to_utc_iso(clock.now()), load["id"]),
        )

    def _task(self, load: dict[str, Any]) -> Task | None:
        if load["task_id"] is None:
            return None
        task = self.board.get(load["task_id"])
        return task if task.status in ("open", "snoozed") else None

    async def _settle_sent(self, task: Task, text: str) -> None:
        """Its nudges already sent stop asking."""
        rows = self.db.query(
            "SELECT member_id, telegram_message_id FROM outbox WHERE status = 'sent' "
            "AND dedupe_key LIKE ? AND telegram_message_id IS NOT NULL",
            (f"task-{task.id}-%",),
        )
        for row in rows:
            member = self.store.get_member(row["member_id"])
            await self.services.outbox.edit(member, row["telegram_message_id"], text)

    def _when(self, local: datetime, today: date) -> str:
        """The time on `today` ("3:40 pm"), or with its day off it ("yesterday at 3:40 pm")."""
        at = clock_words(local)
        days = (local.date() - today).days
        if days == 0:
            return at
        return f"{_day(local.date(), days)} at {at}"

    def _tz(self) -> ZoneInfo:
        family = self.store.get_family()
        return ZoneInfo(family.timezone if family else "UTC")

    def _admin(self) -> Member:
        return next(m for m in self.store.list_members() if m.is_admin)


def _day(day: date, days: int) -> str:
    return {-1: "yesterday", 1: "tomorrow"}.get(days, f"{day:%A}")
