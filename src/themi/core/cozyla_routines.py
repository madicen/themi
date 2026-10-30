"""The wall's routines, and Themi's check-ins on them (C3).

Routines are one person's repeating "did you...?" for a part of the day
(Morning, Afternoon, Evening): walk the dog, cycle the dishwasher, take meds.
The family decided (2026-10-26) that Themi should say when a whole part of
the day's routine isn't done. Each sync (the `cozyla.routines` job):

- Morning and evening checks: after the morning (from noon) and in the
  evening (from an hour before quiet hours), if any of a person's routines
  for that part of the day are still open, one message lists them, with a
  button per routine that ticks it on the wall. All done: nothing is sent.
  Each check also feeds the energy model (as device activity, which the
  person can switch off): a part of the day done is a small lift, one left
  undone a small dip. That's Erin's idea #4 ("are we falling behind?")
  without a dishwasher sensor; people see words, never scores.
- Themi's check-ins (F8: a repeating task made with check_in, on fixed
  days) are that person's routine on the wall, for the part of the day of
  their time, kept by Themi like the chore chart (C2b): put back if changed
  there, made again if deleted. A tick on the wall closes the round; a round
  done in Themi ticks the wall. They're left out of the checks, since Themi
  nudges for them itself.

Wall routines that aren't Themi's stay the wall's: Themi reads them, ticks
them from a button, and never changes them.
"""

from __future__ import annotations

import logging
import re
from dataclasses import replace
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from themi import clock
from themi.accounts import Member
from themi.autonomy import ExecutionContext
from themi.channels.events import Button, InboundEvent
from themi.channels.outbox import Priority
from themi.connectors.cozyla import CozylaClient, CozylaError, Routine, RoutineRecord
from themi.connectors.cozyla.emoji import better_icon, routine_icon
from themi.connectors.cozyla.schedule import to_wall, wall_can_say
from themi.core.cozyla_chores import LOOK_BACK, is_routine
from themi.core.cozyla_todos import backoff, member_map
from themi.core.events import title_matches
from themi.core.groceries import and_list
from themi.core.lists import name_key
from themi.core.repeat import RepeatError, parse, read_back
from themi.core.services import Services
from themi.core.tasks import TaskBoard
from themi.core.tools import Proposal, ToolContext, ToolFailed, staged_tool, tool
from themi.localtime import to_utc_iso

log = logging.getLogger(__name__)

MORNING_CHECK = time(12)
MORNING_CHECK_ENDS = time(17)  # the wall's evening: a morning check after it is no use (#96)
EVENING_BEFORE_QUIET = timedelta(hours=1)
CHECKED_PARTS = ("Morning", "Evening")
ONCE = "today"  # add_to_wall_routine's repeat for just today
JUST_TODAY = re.compile(r"\b(?:today|tonight|just for|this (?:morning|afternoon|evening))\b")
EVERY_DAY = re.compile(  # bug #47: these keep an item, whatever the model sent
    r"\b(?:until further notice|from now on|every (?:day|morning|afternoon|evening|night)|"
    r"always|for good|permanently)\b"
)
CHECK_TEXT = "{part} routine, still open:\n{items}\nDone already?"  # a list (idea #46)
ALL_DONE_TEXT = "{part} routine: all done."
SKIPPED_TEXT = "{part} routine: left for today."
ROUTINE_SIGNAL = 0.5  # a part of the day done, or not: a small lift or dip
PARTS = ("Morning", "Afternoon", "Evening")
ADD_CATEGORY, ADD_EXECUTOR = "wall_routine_add", "cozyla.add_routine"


def part_of_day(at: time | None) -> str:
    """The wall's part of the day for a time: no time counts as the morning."""
    if at is None or at < time(12):
        return "Morning"
    return "Afternoon" if at < time(17) else "Evening"


class CozylaRoutines:
    def __init__(self, services: Services, board: TaskBoard, client: CozylaClient) -> None:
        self.services = services
        self.board = board
        self.client = client
        self.store = services.store
        self.db = services.store.db
        self._read_failures = 0
        self._read_after: datetime | None = None
        self._to_member: dict[str, int] = {}
        self._to_cozyla: dict[int, str] = {}

    def install(self) -> None:
        self.services.button_handlers["routine"] = self.on_button
        self.services.autonomy.executors.register(ADD_EXECUTOR)(self._execute_add)
        self.services.tools.register(add_to_wall_routine)
        self.services.tools.register(show_routine)
        self.services.wall_routines = self

    async def sync(self) -> int:
        """Scheduler job: ticks both ways, Themi's check-ins on the wall, then the morning
        and evening checks. Returns how many checks were sent."""
        if self._read_after is not None and clock.now() < self._read_after:
            return 0
        today = self._today()
        try:
            routines = await self.client.routines()
            members = await self.client.members()
            records = await self.client.routine_records(today)
        except CozylaError as exc:
            log.warning("Cozyla routine sync waits: %s", exc)
            self._read_failures += 1
            self._read_after = clock.now() + backoff(self._read_failures)
            return 0
        self._read_failures, self._read_after = 0, None
        self._to_member = member_map(members, self.store.list_members())
        self._to_cozyla = {mid: uid for uid, mid in self._to_member.items()}
        try:
            await self._expire_once(today)
            await self._ticks_from_wall(today, records)
            await self._ticks_to_wall()
            await self._push({r.id: r for r in routines}, today)
            return await self._checks(today, records)
        except CozylaError as exc:
            log.warning("Cozyla routine sync stopped partway; next time it carries on: %s", exc)
            return 0

    # ----- items added to a routine (bug #22) ----------------------------------------------

    async def _execute_add(self, payload: dict[str, Any], ctx: ExecutionContext) -> str:
        member = self._to_cozyla.get(ctx.member.id)
        if member is None:
            members = await self.client.members()
            mapped = member_map(members, self.store.list_members())
            member = next((uid for uid, mid in mapped.items() if mid == ctx.member.id), None)
        if member is None:
            return "They aren't a member on the wall, so there's no routine to add it to."
        today = self._today()
        phrase = str(payload.get("repeat") or "")
        once = phrase == ONCE or not phrase  # payloads from before F14b: '' was just today
        if "once" in payload:
            once = bool(payload["once"])
        repeat = parse("every day" if once or not phrase else phrase, today)
        title, part = str(payload["title"])[:50], str(payload["part"])
        position = str(payload.get("position") or "end")
        order, where = await self._order(member, part, position)
        schedule = to_wall(repeat, today)
        made = await self.client.create_routine(member, title, part, schedule, order)
        if order is not None:
            where = await self._placed(made, title, part, schedule, today, order, where)
        if once:
            self.db.execute(
                "INSERT OR REPLACE INTO wall_routine_once (routine_id, member_id, day) "
                "VALUES (?, ?, ?)",
                (made, ctx.member.id, today.isoformat()),
            )
            return (
                f"Added {title} to the {part.lower()} routine on the wall{where}, just for today."
            )
        return (
            f"Added {title} to the {part.lower()} routine on the wall{where}: {read_back(repeat)}."
        )

    async def _order(self, member: str, part: str, position: str) -> tuple[float | None, str]:
        """The displayOrder that puts it there (bug #38), and the words for where; None for
        the end, where the wall puts new ones itself."""
        if position == "end":
            return None, ""
        mine = sorted(
            (r for r in await self.client.routines() if (r.member, r.part) == (member, part)),
            key=_display_order,
        )
        if not mine:
            return None, ""
        if position == "start":
            return _display_order(mine[0]) - 1, ", first"
        words = position.removeprefix("after:").strip()
        index = next((i for i, r in enumerate(mine) if title_matches(words, r.title)), None)
        if index is None:
            return None, f" (no item like '{words}' there, so it went at the end)"
        here = _display_order(mine[index])
        after = _display_order(mine[index + 1]) if index + 1 < len(mine) else here + 2
        return (here + after) / 2, f", after {mine[index].title}"

    async def _placed(
        self, routine_id: int, title: str, part: str, schedule: Any, today: date,
        order: float, where: str,
    ) -> str:  # fmt: skip
        """Read it back: the wall may keep its own order. Then once more by an update, and
        if that doesn't take either, say so rather than claim it."""
        for attempt in (1, 2):
            made = next((r for r in await self.client.routines() if r.id == routine_id), None)
            if made is None or _display_order(made) == order:
                return where
            if attempt == 1:
                await self.client.update_routine(made, title, part, schedule, today, order)
        return " (it went at the end: the wall kept its own order, so it needs moving there)"

    async def _expire_once(self, today: date) -> None:
        """Just-for-today items go the day after."""
        for row in self.db.query(
            "SELECT routine_id FROM wall_routine_once WHERE day < ?", (today.isoformat(),)
        ):
            await self.client.delete_routine(row["routine_id"], today)
            self.db.execute(
                "DELETE FROM wall_routine_once WHERE routine_id = ?", (row["routine_id"],)
            )

    # ----- Themi's check-ins as routines ------------------------------------------------------

    async def _ticks_from_wall(self, today: date, records: list[RoutineRecord]) -> None:
        by_day: dict[date, list[RoutineRecord]] = {today: records}
        for link in self.db.query(
            "SELECT r.* FROM cozyla_routines r JOIN tasks t ON t.id = r.task_id "
            "WHERE t.status IN ('open', 'snoozed')"
        ):
            task = self.board.get(link["task_id"])
            days = [d for d in self.board.round_days(task) if today - LOOK_BACK <= d <= today]
            for day in days:  # an either-day round's tick can be on either day (F9a)
                if day not in by_day:
                    by_day[day] = await self.client.routine_records(day)
            records = [r for day in days for r in by_day[day]]
            for record in records:
                if record.routine_id != link["routine_id"] or not record.completed:
                    continue
                if not self._first_time(f"{record.routine_id}_{record.day}"):
                    continue
                doer = self.store.get_member(task.assignee) if task.assignee else self._admin()
                await self.board.complete(task.id, doer)
                self._caught_up(task.id)
                break

    async def _ticks_to_wall(self) -> None:
        for link in self.db.query("SELECT * FROM cozyla_routines"):
            for run in self.db.query(
                "SELECT * FROM task_runs WHERE task_id = ? AND id > ? ORDER BY id",
                (link["task_id"], link["last_run"]),
            ):
                if not run["missed"] and run["due_on"]:
                    day = self.board.done_day(
                        date.fromisoformat(run["due_on"]),
                        datetime.fromisoformat(run["done_at"]),
                        self.board.get(link["task_id"]),
                    )
                    await self.client.check_routine(link["routine_id"], day, True)
                    self._first_time(f"{link['routine_id']}_{day}")
                self.db.execute(
                    "UPDATE cozyla_routines SET last_run = ? WHERE task_id = ?",
                    (run["id"], link["task_id"]),
                )

    async def _push(self, routines: dict[int, Routine], today: date) -> None:
        rows = self.db.query(
            "SELECT t.id FROM tasks t LEFT JOIN cozyla_routines r ON r.task_id = t.id "
            "WHERE r.task_id IS NOT NULL OR (t.status IN ('open', 'snoozed') AND t.check_in = 1)"
        )
        for row in rows:
            task = self.board.get(row["id"])
            link = self.db.one("SELECT * FROM cozyla_routines WHERE task_id = ?", (task.id,))
            routine = routines.get(link["routine_id"]) if link else None
            member = self._to_cozyla.get(task.assignee) if task.assignee else None
            keep = task.status in ("open", "snoozed") and is_routine(task) and member
            if not keep or (routine is not None and routine.member != member):
                if routine is not None:  # stopped, or someone else's now: made again below
                    await self.client.delete_routine(routine.id, today)
                self.db.execute("DELETE FROM cozyla_routines WHERE task_id = ?", (task.id,))
                link = routine = None
            if not keep or member is None or task.repeat is None:
                continue
            title, part = task.title[:50], part_of_day(self.board.time_of(task))
            schedule = to_wall(task.repeat, task.due_on or today)
            if routine is None:
                made = await self.client.create_routine(member, title, part, schedule)
                self.db.execute(
                    "INSERT INTO cozyla_routines (task_id, routine_id, last_run) VALUES (?, ?, ?) "
                    "ON CONFLICT(task_id) DO UPDATE SET routine_id = excluded.routine_id",
                    (task.id, made, self._last_run(task.id)),
                )
                continue
            icon = str(routine.raw.get("routineIcon") or "")
            same = (
                (routine.title, routine.part) == (title, part)
                and (
                    routine.schedule.every,
                    routine.schedule.count,
                    {d.strip() for d in routine.schedule.days.split(",") if d.strip()},
                )
                == (schedule.every, schedule.count, {d for d in schedule.days.split(",") if d})
                and not better_icon(icon, routine_icon(title))  # idea #25
            )
            if not same:
                await self.client.update_routine(routine, title, part, schedule, today)

    # ----- the morning and evening checks -----------------------------------------------------

    async def _checks(self, today: date, records: list[RoutineRecord]) -> int:
        now = clock.now().astimezone(self._tz())
        mine = {r["routine_id"] for r in self.db.query("SELECT routine_id FROM cozyla_routines")}
        sent = 0
        for member in self.store.list_members():
            uid = self._to_cozyla.get(member.id)
            if uid is None or member.telegram_user_id is None:
                continue
            quiet = self._quiet_starts(member, now)
            evening = quiet - EVENING_BEFORE_QUIET
            for part in CHECKED_PARTS:
                start = (
                    now.replace(hour=MORNING_CHECK.hour, minute=0, second=0, microsecond=0)
                    if part == "Morning"
                    else evening
                )
                # The morning's check is no use once the evening starts (it went out at
                # 21:15, then 20:15, held until its deadline): it isn't sent then, and one
                # waiting lapses.
                end = (
                    min(
                        evening,
                        now.replace(
                            hour=MORNING_CHECK_ENDS.hour, minute=0, second=0, microsecond=0
                        ),
                    )
                    if part == "Morning"
                    else quiet
                )
                if not start <= now < end or self._checked(member, today, part):
                    continue
                theirs = [
                    r
                    for r in records
                    if r.member == uid and r.part == part and r.routine_id not in mine
                ]
                if not theirs:
                    continue
                self.db.execute(
                    "INSERT INTO routine_checks_sent (member_id, day, part) VALUES (?, ?, ?)",
                    (member.id, today.isoformat(), part),
                )
                still = [r for r in theirs if not r.completed]
                lift = ROUTINE_SIGNAL if not still else -ROUTINE_SIGNAL
                words = (
                    "done" if not still else f"not finished ({and_list([r.title for r in still])})"
                )
                self.services.energy.record(
                    member, "device_activity", lift, f"{part.lower()} routine {words}"
                )
                if not still:
                    continue
                await self.services.outbox.send(
                    member,
                    CHECK_TEXT.format(part=part, items=_bullets(still)),
                    priority=Priority.NORMAL,
                    kind="routine",
                    buttons=self._buttons(still, today, part),
                    deadline=end - timedelta(minutes=15),
                    dedupe_key=f"routine-{part}-{today}",
                    expires=end,
                )
                sent += 1
        return sent

    @staticmethod
    def _buttons(still: list[RoutineRecord], day: date, part: str) -> list[Button]:
        """A tick for each item, and a way to leave the rest (idea #96: never one button)."""
        return [
            Button(
                f"✓ {r.title}"[:40], "routine", {"routine": r.routine_id, "day": day.isoformat()}
            )
            for r in still
        ] + [Button("Skip today", "routine", {"skip": part, "day": day.isoformat()})]

    async def on_button(self, event: InboundEvent) -> None:
        """A routine's button: tick it on the wall, and show what's left; or leave them."""
        assert event.button is not None
        if "skip" in event.button.payload:
            if event.button.message_id is not None:
                part = str(event.button.payload["skip"])
                await self.services.outbox.edit(
                    event.member, event.button.message_id, SKIPPED_TEXT.format(part=part)
                )
            return
        routine_id = int(event.button.payload["routine"])
        day = date.fromisoformat(str(event.button.payload["day"]))
        try:
            await self.client.check_routine(routine_id, day, True)
            records = await self.client.routine_records(day)
        except CozylaError as exc:
            log.warning("Couldn't tick routine %s on the wall: %s", routine_id, exc)
            text = "The wall couldn't be reached, so that isn't ticked yet. Try again in a bit?"
            if event.button.message_id is not None:
                await self.services.outbox.edit(event.member, event.button.message_id, text)
            return
        self._first_time(f"{routine_id}_{day}")
        ticked = next((r for r in records if r.routine_id == routine_id), None)
        part = ticked.part if ticked else "Morning"
        uid = self._to_cozyla.get(event.member.id) or (ticked.member if ticked else "")
        mine = {r["routine_id"] for r in self.db.query("SELECT routine_id FROM cozyla_routines")}
        still = [
            r
            for r in records
            if r.member == uid and r.part == part and not r.completed and r.routine_id not in mine
        ]
        if event.button.message_id is None:
            return
        if still:
            text = CHECK_TEXT.format(part=part, items=_bullets(still))
            await self.services.outbox.edit(
                event.member, event.button.message_id, text, self._buttons(still, day, part)
            )
        else:
            await self.services.outbox.edit(
                event.member, event.button.message_id, ALL_DONE_TEXT.format(part=part)
            )

    # ----- asked about (bugs #76 and #78) ---------------------------------------------------

    async def describe(self, member: Member, part: str) -> str:
        """Their routine on the wall today, for one part of the day or all three."""
        try:
            members = await self.client.members()
            records = await self.client.routine_records(self._today())
        except CozylaError as exc:
            raise ToolFailed(f"The wall couldn't be reached ({exc}); say so.") from exc
        uid = next(
            (
                u
                for u, m in member_map(members, self.store.list_members()).items()
                if m == member.id
            ),
            None,
        )
        if uid is None:
            return f"{member.name} isn't a member on the wall, so they have no routines there."
        lines = []
        for each in [part] if part in PARTS else PARTS:
            items = [
                f"{r.title}{' (done)' if r.completed else ''}"
                for r in records
                if r.member == uid and r.part == each
            ]
            lines.append(
                f"{each} routine on the wall, today: {', '.join(items)}."
                if items
                else f"Nothing on the {each.lower()} routine on the wall today."
            )
        return " ".join(lines) + " Say it in words, as a short list."

    # ----- small things -------------------------------------------------------------------

    def _checked(self, member: Member, day: date, part: str) -> bool:
        return bool(
            self.db.one(
                "SELECT 1 FROM routine_checks_sent WHERE member_id = ? AND day = ? AND part = ?",
                (member.id, day.isoformat(), part),
            )
        )

    @staticmethod
    def _quiet_starts(member: Member, now: datetime) -> datetime:
        at = member.quiet_start
        start = now.replace(hour=at.hour, minute=at.minute, second=0, microsecond=0)
        return start + timedelta(days=1) if at < time(12) else start

    def _caught_up(self, task_id: int) -> None:
        self.db.execute(
            "UPDATE cozyla_routines SET last_run = ? WHERE task_id = ?",
            (self._last_run(task_id), task_id),
        )

    def _last_run(self, task_id: int) -> int:
        return self.db.scalar(
            "SELECT COALESCE(MAX(id), 0) FROM task_runs WHERE task_id = ?", (task_id,)
        )

    def _first_time(self, record: str) -> bool:
        if self.db.one("SELECT 1 FROM cozyla_routine_ticks WHERE record = ?", (record,)):
            return False
        self.db.execute(
            "INSERT INTO cozyla_routine_ticks (record, seen_at) VALUES (?, ?)",
            (record, to_utc_iso(clock.now())),
        )
        return True

    def _today(self) -> date:
        return clock.now().astimezone(self._tz()).date()

    def _tz(self) -> ZoneInfo:
        family = self.store.get_family()
        return ZoneInfo(family.timezone if family else "UTC")

    def _admin(self) -> Member:
        return next(m for m in self.store.list_members() if m.is_admin)


@staged_tool(
    "add_to_wall_routine",
    "Add an item to someone's morning, afternoon or evening routine on the Cozyla wall "
    "('add replace vacuum water to my evening routine tonight'). repeat: 'today' for just "
    "today or tonight, a schedule phrase ('every Tue and Thu'), or '' for every day. "
    "position: 'end', 'start', or 'after: <item>'; several at the start, in order: the "
    "first 'start', each next 'after: <the one before>'. Not a calendar event, a chore or "
    "a list.",
    {
        "title": {"type": "string"},
        "part": {"type": "string", "enum": list(PARTS)},
        "repeat": {"type": "string"},
        "position": {"type": "string"},
    },
)
async def add_to_wall_routine(ctx: ToolContext, args: dict[str, Any]) -> Proposal:
    if ctx.services.wall_routines is None:
        raise ToolFailed("The wall's routines aren't connected.")
    title = " ".join(str(args["title"]).split())[:50]
    if not title:
        raise ToolFailed("A routine item needs a name.")
    phrase = " ".join(str(args["repeat"]).split())
    said = name_key(ctx.request_text)
    if phrase.lower() in (ONCE, "tonight", "just today"):
        phrase, once = "", True
    else:
        once = not phrase and bool(JUST_TODAY.search(said))  # '' is every day (bug #38)
    once = once and not EVERY_DAY.search(said)
    if phrase:
        try:
            repeat = parse(phrase, ctx.services.wall_routines._today())
        except RepeatError as exc:
            raise ToolFailed(str(exc)) from exc
        if not wall_can_say(repeat):
            raise ToolFailed("The wall's routines can't repeat like that; try 'every Tue and Thu'.")
    when = ", just today" if once else f", {phrase}" if phrase else ", every day"
    position = " ".join(str(args.get("position") or "end").split()).lower() or "end"
    if position not in ("start", "end") and not position.startswith("after:"):
        raise ToolFailed("position: 'start', 'end' or 'after: <item>'.")
    words = [w for w in name_key(title).split() if len(w) > 2]
    asked = "routine" in said and all(w in said for w in words)
    proposal = Proposal(
        ADD_CATEGORY,
        f"{title} for the {str(args['part']).lower()} routine{when}",
        ADD_EXECUTOR,
        {
            "title": title,
            "part": args["part"],
            "repeat": phrase,
            "once": once,
            "position": position,
        },
    )
    return replace(proposal, requested=asked)


@tool(
    "show_routine",
    "Read someone's routine on the Cozyla wall, as it is today: its items in order, and "
    "which are done. part: 'Morning', 'Afternoon' or 'Evening', or '' for all three. For "
    "'what's my morning routine?'; not the day's calendar.",
    {"part": {"type": "string", "enum": ["", *PARTS]}},
)
async def show_routine(ctx: ToolContext, args: dict[str, Any]) -> str:
    if ctx.services.wall_routines is None:
        raise ToolFailed("The wall's routines aren't connected.")
    return await ctx.services.wall_routines.describe(ctx.member, str(args["part"]))


def _display_order(routine: Routine) -> float:
    return float(routine.raw.get("displayOrder") or 0)


def _bullets(still: list[RoutineRecord]) -> str:
    return "\n".join(f"- {r.title}" for r in still)
