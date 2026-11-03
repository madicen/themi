"""The robot vacuum's chores (V1): when it needs a person, someone hears about it.

From the robot's events (Roborock, `themi.connectors.roborock`):

- A problem starting (stuck, a jam, the dock's water empty or full, a dustbin out, not back
  on its dock, any other fault) makes one effort-1 hands-on task, for whoever has the most
  room right now, off the wall's lists like the laundry's (it comes and goes with the
  robot). Starting while that person's in quiet hours, it's for either of you instead
  (F23d: at 4:47 am the pick is a guess): on both lists, each asked as their quiet hours
  end, and whoever does it closes it. Its nudge waits 5 minutes (half an hour for "not
  back on its dock": it may still be sent home), so a problem sorted at once never sends
  one; then it asks, naming the room when the map says, and the chore goes on the wall's
  to-do list (F23d, the `vacuum.wall` job), so one sorted at once never shows there.
  Done / Later; Later asks again in an hour.
- The robot showing the problem's gone closes the task: done if the nudge had gone out
  (someone most likely saw to it), quietly taken off the list if not.
- Once a stuck, jammed or binned robot is sorted and it's sitting off its dock, or someone
  says a chore's done while the robot still shows its alert (a dock's water alert stays
  until it's cleared), Themi offers to clear the alert and send it home: a side effect, so
  it's staged in `vacuum_home`, a card until a rule makes it automatic.
- A part nearly worn out makes a "Replace the vacuum's filter" task, once until the part's
  counter is reset in the Roborock app. Not time-bound: the usual daily limit applies.

Asked how the vacuum is (`appliance_status`), each open chore is said with whose it is
and whether they've been asked (F23d).

People see words, never codes. A problem marked done isn't raised again until the robot
stops showing it.
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta
from typing import Any

from themi import clock
from themi.accounts import Device, Member
from themi.autonomy import ExecutionContext
from themi.channels.outbox import Button, Priority
from themi.connectors.roborock import (
    BIN,
    FAULT,
    JAMMED,
    NOT_DOCKED,
    PART,
    STUCK,
    WATER_EMPTY,
    WATER_FULL,
    RoborockError,
    RoborockWatcher,
    VacuumEvent,
)
from themi.core.services import Services
from themi.core.tasks import Task, TaskBoard, TaskChange, clock_words
from themi.localtime import in_quiet_hours, to_local, to_utc_iso

log = logging.getLogger(__name__)

KIND = "vacuum"  # the outbox kind: "/pause vacuum" holds these
CATEGORY, EXECUTOR = "vacuum_home", "devices.vacuum_home"
TITLES = {
    STUCK: "Free the stuck vacuum",
    JAMMED: "Unjam the vacuum",
    WATER_EMPTY: "Refill the vacuum's clean water",
    WATER_FULL: "Empty the vacuum's dirty water",
    BIN: "Check the vacuum's dustbin",
    NOT_DOCKED: "Put the vacuum back on its dock",
    FAULT: "Check the vacuum",
}
TEXTS = {
    STUCK: "The vacuum's stuck{where} ({detail}). Free it and pop it back on the dock?",
    JAMMED: "The vacuum needs a hand{where}: {detail}. Clear it when you can?",
    WATER_EMPTY: "The vacuum's dock is out of clean water. Refill the tank?",
    WATER_FULL: "The vacuum's dock needs emptying ({detail}). Empty the tank?",
    BIN: "The vacuum needs a hand: {detail}. Sort it when you can?",
    NOT_DOCKED: "The vacuum didn't make it back to its dock{where} ({detail}). Carry it back?",
    FAULT: "The vacuum needs a look: {detail}. Check it when you can?",
}
PART_TITLE, PART_TEXT = (
    "Replace the vacuum's {part}",
    "The vacuum's {part} is nearly worn out. Replace it when you can?",
)
SENSORS_TITLE, SENSORS_TEXT = (
    "Wipe the vacuum's sensors",
    "The vacuum's sensors are due a wipe. Clean them when you can?",
)
EXPIRED_TEXT = (
    "The Roborock sign-in stopped working, so Themi can't see the vacuum for now. It can "
    "be linked again on the Family page."
)
DONE, LATER = "Done", "Later"
WAIT = timedelta(minutes=5)  # a problem's first nudge waits this long
AWAY_WAIT = timedelta(minutes=30)  # "not back on its dock" waits longer: it may be sent home
LATER_FOR = 60  # minutes: Later asks again in an hour
HOME_AFTER = (STUCK, JAMMED, BIN, FAULT)  # sorted, it may be sitting where it stopped
CARD_FOR = timedelta(hours=2)  # an offer to send it home goes stale


class Vacuum:
    def __init__(self, services: Services, board: TaskBoard, watcher: RoborockWatcher) -> None:
        self.services = services
        self.board = board
        self.watcher = watcher
        self.store = services.store
        self.db = services.store.db

    def install(self) -> None:
        self.services.vacuum = self
        self.services.autonomy.executors.register(EXECUTOR)(self._execute)
        self.watcher.listeners.append(self.on_event)
        self.watcher.expired_listeners.append(self._expired)
        self.board.own_nudges.append(self._nudge)
        self.board.change_listeners.append(self._task_changed)

    # ----- the robot ------------------------------------------------------------------

    async def on_event(self, event: VacuumEvent) -> None:
        problem = f"{PART}:{event.detail}" if event.kind == PART else event.kind
        if event.gone:
            await self._gone(event, problem)
            return
        if self._live(event.device_id, problem):
            return  # still the one already raised (or done, and not yet gone)
        assignment = self.board.matcher.roomiest("physical", 1, event.at)
        row_id = self.db.execute(
            "INSERT INTO vacuum_problems (device_id, problem, detail, room, status, opened_at) "
            "VALUES (?, ?, ?, ?, 'open', ?)",
            (event.device_id, problem, event.detail, event.room, to_utc_iso(event.at)),
        )
        task = await self.board.create(
            assignment.assignee,
            _title(event.kind, event.detail),
            "physical",
            1,
            nudge=False,
            off_wall=True,  # it comes and goes with the robot; the wall's lists stay calm
            assignment=assignment,
        )
        self.db.execute("UPDATE vacuum_problems SET task_id = ? WHERE id = ?", (task.id, row_id))
        if in_quiet_hours(assignment.assignee, event.at, self._timezone()):
            await self.board.make_either(task.id)  # each asked as they wake; first one wins
        else:
            await self.board.prompt(task)  # now it's known as the robot's: its own nudge

    async def _gone(self, event: VacuumEvent, problem: str) -> None:
        now = to_utc_iso(event.at)
        for row in self._live(event.device_id, problem):
            self.db.execute("UPDATE vacuum_problems SET gone_at = ? WHERE id = ?", (now, row["id"]))
            if row["status"] != "open":
                continue
            self.db.execute(
                "UPDATE vacuum_problems SET status = 'cleared', closed_at = ? WHERE id = ?",
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
            if event.kind in HOME_AFTER:
                await self._offer_home(event.device_id, member)

    # ----- clearing its alert, sending it home -----------------------------------------------

    async def _offer_home(self, device_id: int, member: Member) -> None:
        """When it still shows an alert, or sits off its dock: a card to clear it and send
        it home."""
        device = self._device(device_id)
        if device is None:
            return
        alert = any(kind != NOT_DOCKED for kind in self.watcher.problems(device))
        away = self.watcher.states().get(device.id) in ("away from its dock", "paused")
        if alert and away:
            summary = "Clear the vacuum's alert and send it back to its dock"
        elif alert:
            summary = "Clear the vacuum's alert"
        elif away:
            summary = "Send the vacuum back to its dock"
        else:
            return
        await self.services.autonomy.stage(
            CATEGORY,
            member,
            summary,
            {"device": device.id},
            EXECUTOR,
            expires=clock.now() + CARD_FOR,
        )

    async def _execute(self, payload: dict[str, Any], ctx: ExecutionContext) -> str:
        device = self._device(int(payload["device"]))
        if device is None:
            return "The vacuum isn't linked any more, so nothing was sent."
        try:
            status = await self.watcher.read(device)
            done = []
            if status.alert:
                await self.watcher.resolve(device, status.alert)
                done.append("cleared the vacuum's alert")
            if not (status.docked or status.cleaning or status.returning):
                await self.watcher.send_home(device)
                done.append("sent it back to its dock")
        except RoborockError as exc:
            log.warning("Couldn't send the vacuum home: %s", exc)
            return "The vacuum couldn't be reached, so nothing was sent."
        if not done:
            return "The vacuum's already fine, so there was nothing to do."
        said = " and ".join(done)
        return said[0].upper() + said[1:] + "."

    # ----- the nudge ------------------------------------------------------------------

    async def _nudge(
        self, task: Task, member: Member, not_before: datetime | None, deadline: datetime | None
    ) -> bool:
        row = self.db.one("SELECT * FROM vacuum_problems WHERE task_id = ?", (task.id,))
        if row is None:
            return False
        if row["status"] != "open":
            return True  # already handled; nothing to ask
        now = clock.now()
        kind, _, part = str(row["problem"]).partition(":")
        if kind == PART:
            text = SENSORS_TEXT if part == "sensors" else PART_TEXT.format(part=part)
        else:
            text = TEXTS[kind].format(where=_where(row["room"]), detail=row["detail"])
            # Time-bound: due when it may go, so the daily limit doesn't hold it to morning.
            # Quiet hours, busy times and a pause still do.
            opened = datetime.fromisoformat(row["opened_at"])
            wait = AWAY_WAIT if kind == NOT_DOCKED else WAIT
            not_before = max(now, opened + wait, not_before or now)
            deadline = not_before
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
        """Done or taken off the list by a person (a tap, a word in chat): the problem's
        handled as far as Themi's concerned. If the robot still shows it, or sits off its
        dock, Themi offers to clear the alert and send it home."""
        if change not in ("done", "cancelled"):
            return
        row = self.db.one(
            "SELECT * FROM vacuum_problems WHERE task_id = ? AND status = 'open'", (task.id,)
        )
        if row is None:
            return
        self.db.execute(
            "UPDATE vacuum_problems SET status = 'done', closed_at = ? WHERE id = ?",
            (to_utc_iso(clock.now()), row["id"]),
        )
        if change == "done" and not str(row["problem"]).startswith(PART) and task.assignee:
            await self._offer_home(int(row["device_id"]), self.store.get_member(task.assignee))

    async def _expired(self, why: str) -> None:
        for member in self.store.list_members():
            if member.is_admin:
                await self.services.outbox.send(
                    member,
                    EXPIRED_TEXT,
                    priority=Priority.NORMAL,
                    kind=KIND,
                    dedupe_key=f"roborock-expired-{clock.now().date().isoformat()}",
                )

    async def onto_wall(self) -> int:
        """Scheduler job: a problem still open once its nudge may go puts its chore on the
        wall's to-do list. Returns how many went on."""
        now = clock.now()
        put = 0
        for row in self.db.query(
            "SELECT p.*, t.off_wall FROM vacuum_problems p JOIN tasks t ON t.id = p.task_id "
            "WHERE p.status = 'open' AND t.off_wall = 1 AND t.status IN ('open', 'snoozed')"
        ):
            wait = AWAY_WAIT if row["problem"] == NOT_DOCKED else WAIT
            if datetime.fromisoformat(row["opened_at"]) + wait <= now:
                await self.board.put_on_wall(int(row["task_id"]))
                put += 1
        return put

    # ----- asked about ------------------------------------------------------------------

    def chores(self, device_id: int) -> list[str]:
        """Each open chore for the robot: whose it is, and whether they've been asked."""
        lines = []
        for row in self.db.query(
            "SELECT * FROM vacuum_problems WHERE device_id = ? AND status = 'open' "
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

    def _timezone(self) -> str:
        family = self.store.get_family()
        return family.timezone if family else "UTC"

    def _live(self, device_id: int, problem: str) -> list[dict[str, Any]]:
        return self.db.query(
            "SELECT * FROM vacuum_problems WHERE device_id = ? AND problem = ? "
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


def _title(kind: str, detail: str) -> str:
    if kind == PART:
        return SENSORS_TITLE if detail == "sensors" else PART_TITLE.format(part=detail)
    return TITLES[kind]


def _where(room: str | None) -> str:
    """ " in the kitchen", from the Roborock app's room name ("Kitchen"; "Erin's room")."""
    if not room:
        return ""
    if "'" in room:
        return f" in {room}"
    return f" in the {room.lower()}"
