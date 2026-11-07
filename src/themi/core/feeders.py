"""The pet feeders' chores (32): when a feeder needs a person, someone hears about it.

From the feeders' events (Tuya, `themi.connectors.tuya`):

- Food running low or out, the food stuck, or another fault makes one effort-1 hands-on
  task, for whoever has the most room right now (`Matcher.roomiest`, as the laundry's). It
  goes on the wall's lists like any chore: it lasts until someone sees to it. Starting while
  that person's in quiet hours, it's for either of you instead (as the vacuum's, F23d).
- Its nudge waits 10 minutes, so a reading that bounces never sends one. Out of food or
  stuck, the pet misses a meal, so it's due at once (the daily limit doesn't hold it to
  morning; quiet hours, busy times and "/pause feeders" still do). Running low or another
  fault can wait for the usual limits. Done / Later; Later asks again in an hour.
- Running low, then out: the same task, asked again with the new words.
- The feeder showing it's sorted closes the task: done if the nudge had gone out, quietly
  taken off the list if not.
- Energy: someone saying they've done one is a small chore's effort for them (a "device
  activity" signal, kept only when that input is on for them), so the next one leans to
  whoever has more room. The feeder
  sorting itself says nothing about who did it, and nor do its feedings, so neither counts.

People see words, never codes. A problem marked done isn't raised again until the feeder
stops showing it.
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta
from typing import Any

from themi import clock
from themi.accounts import Device, Member
from themi.channels.outbox import Button, Priority
from themi.connectors.tuya import FAULT, FOOD, JAMMED, OUT, FeederEvent, TuyaWatcher
from themi.core import keys
from themi.core.services import Services
from themi.core.tasks import Task, TaskBoard, TaskChange, clock_words
from themi.localtime import in_quiet_hours, to_local, to_utc_iso

log = logging.getLogger(__name__)

KIND = "feeder"  # the outbox kind: "/pause feeders" holds these
TITLES = {
    FOOD: "Refill {the}",
    JAMMED: "Unjam {the}",
    FAULT: "Check {the}",
}
LOW_TEXT = "{The} is running low on food{left}. Top it up when you can?"
OUT_TEXT = "{The} is out of food. Fill it before the next meal?"
TEXTS = {
    JAMMED: "{The} needs a hand: {detail}. Clear it so the next meal comes out?",
    FAULT: "{The} needs a look: {detail}. Check it when you can?",
}
BROKEN_TEXT = (
    "Tuya stopped answering for the feeders, so Themi can't see them for now: {why} It can be "
    "linked again on the website's Accounts page."
)
DONE, LATER = "Done", "Later"
WAIT = timedelta(minutes=10)  # a problem's first nudge waits this long
LATER_FOR = 60  # minutes: Later asks again in an hour
URGENT = (JAMMED,)  # with OUT: a meal would be missed
EFFORT = -0.5  # a small chore, for the energy model


class Feeders:
    def __init__(self, services: Services, board: TaskBoard, watcher: TuyaWatcher) -> None:
        self.services = services
        self.board = board
        self.watcher = watcher
        self.store = services.store
        self.db = services.store.db

    def install(self) -> None:
        self.services.provide(keys.feeders, self)
        self.watcher.listeners.append(self.on_event)
        self.watcher.broken_listeners.append(self._broken)
        self.board.own_nudges.append(self._nudge)
        self.board.change_listeners.append(self._task_changed)
        self.board.done_hooks.append(self._done)

    # ----- the feeder -------------------------------------------------------------------

    async def on_event(self, event: FeederEvent) -> None:
        if event.gone:
            await self._gone(event)
            return
        live = self._live(event.device_id, event.kind)
        if live:
            await self._changed(live[-1], event)
            return
        device = self._device(event.device_id)
        if device is None:
            return
        assignment = self.board.matcher.roomiest("physical", 1, event.at)
        row_id = self.db.execute(
            "INSERT INTO feeder_problems (device_id, problem, detail, status, opened_at) "
            "VALUES (?, ?, ?, 'open', ?)",
            (event.device_id, event.kind, event.detail, to_utc_iso(event.at)),
        )
        task = await self.board.create(
            assignment.assignee,
            TITLES[event.kind].format(the=_the(device.name)),
            "physical",
            1,
            nudge=False,
            assignment=assignment,
        )
        self.db.execute("UPDATE feeder_problems SET task_id = ? WHERE id = ?", (task.id, row_id))
        if in_quiet_hours(assignment.assignee, event.at, self._timezone()):
            await self.board.make_either(task.id)  # each asked as they wake; first one wins
        else:
            await self.board.prompt(task)  # now it's known as the feeder's: its own nudge

    async def _changed(self, row: dict[str, Any], event: FeederEvent) -> None:
        """The same problem in new words. Running low, then out: asked again, if it's open."""
        if row["detail"] == event.detail:
            return
        self.db.execute(
            "UPDATE feeder_problems SET detail = ? WHERE id = ?", (event.detail, row["id"])
        )
        task = self._task(row)
        if row["status"] == "open" and task is not None and event.detail == OUT:
            await self.board.prompt(task)

    async def _gone(self, event: FeederEvent) -> None:
        now = to_utc_iso(event.at)
        for row in self._live(event.device_id, event.kind):
            self.db.execute("UPDATE feeder_problems SET gone_at = ? WHERE id = ?", (now, row["id"]))
            if row["status"] != "open":
                continue
            # Closed before the task, so `_task_changed` doesn't take it for a person's word.
            self.db.execute(
                "UPDATE feeder_problems SET status = 'cleared', closed_at = ? WHERE id = ?",
                (now, row["id"]),
            )
            task = self._task(row)
            if task is None or task.assignee is None:
                continue
            member = self.store.get_member(task.assignee)
            if self._sent(task):
                await self.board.complete(task.id, member)
            else:
                await self.board.cancel(task.id, member)

    # ----- the nudge ------------------------------------------------------------------

    async def _nudge(
        self, task: Task, member: Member, not_before: datetime | None, deadline: datetime | None
    ) -> bool:
        row = self.db.one("SELECT * FROM feeder_problems WHERE task_id = ?", (task.id,))
        if row is None:
            return False
        if row["status"] != "open":
            return True  # already handled; nothing to ask
        device = self._device(int(row["device_id"])) if row["device_id"] else None
        the = _the(device.name if device else "feeder")
        now = clock.now()
        kind, detail = str(row["problem"]), str(row["detail"])
        not_before = max(now, datetime.fromisoformat(row["opened_at"]) + WAIT, not_before or now)
        if kind == FOOD and detail == OUT:
            text = OUT_TEXT.format(The=_cap(the))
        elif kind == FOOD:
            text = LOW_TEXT.format(The=_cap(the), left=self._left(row))
        else:
            text = TEXTS[kind].format(The=_cap(the), detail=detail)
        if kind in URGENT or detail == OUT:
            deadline = not_before  # due when it may go: the daily limit doesn't hold it
        self._withdraw(task, member)  # one nudge per problem waiting for them
        result = await self.services.outbox.send(
            member,
            text,
            priority=Priority.NORMAL,
            kind=KIND,
            buttons=[
                Button(DONE, "task", {"task": task.id, "action": "done"}),
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
        """Done or taken off the list by a person (a tap, a word in chat, a tick on the wall):
        handled as far as Themi's concerned."""
        if change not in ("done", "cancelled"):
            return
        self.db.execute(
            "UPDATE feeder_problems SET status = 'done', closed_at = ? "
            "WHERE task_id = ? AND status = 'open'",
            (to_utc_iso(clock.now()), task.id),
        )

    async def _done(self, task: Task, by: Member, interactive: bool) -> None:
        """Someone did it: a small chore's effort for them. Not when the feeder showed it
        sorted (that's 'cleared'), which says nothing about who did it."""
        row = self.db.one(
            "SELECT * FROM feeder_problems WHERE task_id = ? AND status = 'done'", (task.id,)
        )
        if row is not None:
            note = f"saw to the feeder ({row['problem']})"
            self.services.energy.record(by, "device_activity", EFFORT, note)

    async def _broken(self, why: str) -> None:
        for member in self.store.list_members():
            if member.is_admin:
                await self.services.outbox.send(
                    member,
                    BROKEN_TEXT.format(why=why),
                    priority=Priority.NORMAL,
                    kind=KIND,
                    dedupe_key=f"tuya-broken-{clock.now().date().isoformat()}",
                )

    # ----- asked about ------------------------------------------------------------------

    def chores(self, device_id: int) -> list[str]:
        """Each open chore for the feeder: whose it is, and whether they've been asked."""
        lines = []
        for row in self.db.query(
            "SELECT * FROM feeder_problems WHERE device_id = ? AND status = 'open' "
            "AND task_id IS NOT NULL ORDER BY id",
            (device_id,),
        ):
            task = self._task(row)
            if task is None:
                continue
            if task.either:
                whose = "either of you"
            elif task.assignee is not None:
                whose = f"{self.store.get_member(task.assignee).name}'s"
            else:
                whose = "nobody's yet"
            asked = self.db.scalar(
                "SELECT MIN(sent_at) FROM outbox WHERE status = 'sent' AND dedupe_key LIKE ?",
                (f"task-{task.id}-%",),
            )
            when = (
                f"asked at {clock_words(to_local(datetime.fromisoformat(asked), self._timezone()))}"
                if asked
                else "not asked yet"
            )
            lines.append(f"Open chore: {task.title}, {whose}, {when}.")
        return lines

    # ----- small things -------------------------------------------------------------------

    def _withdraw(self, task: Task, member: Member) -> None:
        """Before a new nudge: this person's waiting ones go. A chore for either of you keeps
        the other's."""
        if not task.shared:
            self.board.withdraw_prompt(task)
            return
        for queued in self.db.query(
            "SELECT id FROM outbox WHERE status = 'queued' AND member_id = ? AND dedupe_key LIKE ?",
            (member.id, f"task-{task.id}-%"),
        ):
            self.services.outbox.cancel(queued["id"])

    def _left(self, row: dict[str, Any]) -> str:
        level = self.db.scalar(
            "SELECT level FROM feeder_states WHERE device_id = ?", (row["device_id"],)
        )
        return f" (about {level}% left)" if level is not None else ""

    def _timezone(self) -> str:
        family = self.store.get_family()
        return family.timezone if family else "UTC"

    def _live(self, device_id: int, problem: str) -> list[dict[str, Any]]:
        return self.db.query(
            "SELECT * FROM feeder_problems WHERE device_id = ? AND problem = ? "
            "AND gone_at IS NULL ORDER BY id",
            (device_id, problem),
        )

    def _task(self, row: dict[str, Any]) -> Task | None:
        if row["task_id"] is None:
            return None
        task = self.board.get(row["task_id"])
        return task if task.status in ("open", "snoozed") else None

    def _sent(self, task: Task) -> bool:
        return (
            self.db.one(
                "SELECT 1 FROM outbox WHERE status = 'sent' AND dedupe_key LIKE ?",
                (f"task-{task.id}-%",),
            )
            is not None
        )

    def _device(self, device_id: int) -> Device | None:
        return next((d for d in self.watcher.devices() if d.id == device_id), None)


def _the(name: str) -> str:
    """ "the cat feeder" from the SmartLife app's "Cat Feeder"; "Mochi's feeder" as it is."""
    name = name.strip() or "feeder"
    if "'" in name or "\u2019" in name:
        return name
    return f"the {name.lower()}"


def _cap(words: str) -> str:
    return words[0].upper() + words[1:]
