"""Routines kept in Themi (R1a, Erin's idea #79).

Each person has routines: a name and a time window, local time. Everyone starts
with Morning (8 to 12), Afternoon (12 to 5) and Evening (5 until an hour before
their quiet hours, as C3's evening check), and can add, re-time, rename or
remove them in chat. A routine's items apply every day, on set days, or just
one day, and are ticked once a day.

The check (the `routines.check` job): once a routine's window ends, if any of
today's items are open, one message lists them, with a button per item and
"Skip today", as C3's checks. All done: nothing is sent. Each check feeds the
energy model as device activity (a small lift or dip, in words), which each
person can switch off.

Changes to your own routines are done when asked. An item for someone else's
routine goes through `routine_item_add`. The wall isn't touched yet (R1b): C3
keeps checking the wall's routines as before.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from themi import clock
from themi.accounts import Member
from themi.autonomy import ExecutionContext
from themi.channels.events import Button, InboundEvent
from themi.channels.outbox import Priority
from themi.core.cozyla_routines import (
    ALL_DONE_TEXT,
    CHECK_TEXT,
    EVENING_BEFORE_QUIET,
    ROUTINE_SIGNAL,
    SKIPPED_TEXT,
)
from themi.core.events import title_matches
from themi.core.groceries import and_list
from themi.core.lists import name_key
from themi.core.services import Services
from themi.core.tools import Proposal, ToolContext, ToolFailed, staged_tool, tool
from themi.localtime import to_utc_iso

log = logging.getLogger(__name__)

DEFAULTS = (
    ("Morning", time(8), time(12)),
    ("Afternoon", time(12), time(17)),
    ("Evening", time(17), None),
)
# A check this long after its window ended isn't sent, and one waiting lapses: Morning's
# at 5 pm, when the evening starts (idea #96).
CHECK_LATE = timedelta(hours=5)
DAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
ADD_CATEGORY, ADD_EXECUTOR = "routine_item_add", "routines.add_item"
KIND = "routine"  # the outbox kind, as C3's checks


@dataclass(frozen=True)
class Routine:
    id: int
    member_id: int
    name: str
    starts: time
    ends: time | None  # None: until an hour before quiet hours


@dataclass(frozen=True)
class Item:
    id: int
    routine_id: int
    title: str
    days: tuple[int, ...]  # empty: every day
    only_on: date | None

    def applies(self, day: date) -> bool:
        if self.only_on is not None:
            return day == self.only_on
        return not self.days or day.weekday() in self.days

    def when(self) -> str:
        if self.only_on is not None:
            return f"just {self.only_on:%A %-d %B}"
        if not self.days:
            return "every day"
        return "on " + and_list([DAY_NAMES[d] + "s" for d in self.days])


def _routine(row: dict[str, Any]) -> Routine:
    return Routine(
        row["id"],
        row["member_id"],
        row["name"],
        time.fromisoformat(row["starts"]),
        time.fromisoformat(row["ends"]) if row["ends"] else None,
    )


def _item(row: dict[str, Any]) -> Item:
    return Item(
        row["id"],
        row["routine_id"],
        row["title"],
        tuple(json.loads(row["days"])),
        date.fromisoformat(row["only_on"]) if row["only_on"] else None,
    )


def clock_text(at: time) -> str:
    hour = at.hour % 12 or 12
    suffix = "am" if at.hour < 12 else "pm"
    return f"{hour}:{at.minute:02d} {suffix}" if at.minute else f"{hour} {suffix}"


class Routines:
    def __init__(self, services: Services) -> None:
        self.services = services
        self.store = services.store
        self.db = services.store.db
        # Told of each tick made in Themi, so the wall shows it at once (R1b).
        self.tick_listeners: list[Callable[[Item, date], Awaitable[None]]] = []

    def install(self) -> None:
        self.services.routines = self
        self.services.button_handlers["routine_item"] = self.on_button
        self.services.autonomy.executors.register(ADD_EXECUTOR)(self._execute_add)
        for each in (show_routines, set_routine, remove_routine, add_routine_item,
                     remove_routine_item, tick_routine_item):  # fmt: skip
            self.services.tools.register(each)

    # ----- routines ---------------------------------------------------------------------

    def of(self, member: Member) -> list[Routine]:
        """Their routines, by start time; the three defaults the first time."""
        if not self.db.one("SELECT 1 FROM routines WHERE member_id = ?", (member.id,)):
            for name, starts, ends in DEFAULTS:
                self._insert(member, name, starts, ends)
        rows = self.db.query(
            "SELECT * FROM routines WHERE member_id = ? ORDER BY starts, id", (member.id,)
        )
        return [_routine(r) for r in rows]

    def find(self, member: Member, name: str) -> Routine | None:
        wanted = name_key(name).removesuffix(" routine").strip()
        return next((r for r in self.of(member) if name_key(r.name) == wanted), None)

    def set(
        self, member: Member, name: str, starts: time, ends: time | None, new_name: str = ""
    ) -> tuple[Routine, bool]:
        """Add a routine, or re-time (and rename) one. Returns it, and whether it's new."""
        if ends is not None and ends <= starts:
            raise ValueError("A routine has to end after it starts, on the same day.")
        found = self.find(member, name)
        if found is None:
            return self._insert(member, name, starts, ends), True
        title = (new_name or found.name).strip()[:40]
        if title.lower() != found.name.lower() and self.find(member, title):
            raise ValueError(f"There's already a routine called {title}.")
        self.db.execute(
            "UPDATE routines SET name = ?, starts = ?, ends = ? WHERE id = ?",
            (title, starts.strftime("%H:%M"), ends.strftime("%H:%M") if ends else None, found.id),
        )
        return self.get(found.id), False

    def remove(self, routine: Routine) -> None:
        self.db.execute("DELETE FROM routines WHERE id = ?", (routine.id,))

    def window(self, routine: Routine, member: Member) -> str:
        ends = clock_text(routine.ends) if routine.ends else "an hour before your quiet hours"
        return f"{clock_text(routine.starts)} to {ends}"

    def _insert(self, member: Member, name: str, starts: time, ends: time | None) -> Routine:
        routine_id = self.db.execute(
            "INSERT INTO routines (member_id, name, starts, ends, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                member.id,
                " ".join(name.split())[:40],
                starts.strftime("%H:%M"),
                ends.strftime("%H:%M") if ends else None,
                to_utc_iso(clock.now()),
            ),
        )
        return self.get(routine_id)

    def get(self, routine_id: int) -> Routine:
        row = self.db.one("SELECT * FROM routines WHERE id = ?", (routine_id,))
        assert row is not None
        return _routine(row)

    # ----- items ------------------------------------------------------------------------

    def item(self, item_id: int) -> Item | None:
        row = self.db.one("SELECT * FROM routine_items WHERE id = ?", (item_id,))
        return _item(row) if row else None

    def items(self, routine: Routine) -> list[Item]:
        rows = self.db.query(
            "SELECT * FROM routine_items WHERE routine_id = ? ORDER BY position, id", (routine.id,)
        )
        return [_item(r) for r in rows]

    def add_item(
        self, routine: Routine, title: str, days: tuple[int, ...] = (), only_on: date | None = None
    ) -> Item:
        position = self.db.scalar(
            "SELECT COALESCE(MAX(position), 0) + 1 FROM routine_items WHERE routine_id = ?",
            (routine.id,),
        )
        item_id = self.db.execute(
            "INSERT INTO routine_items (routine_id, title, days, only_on, position, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                routine.id,
                " ".join(title.split())[:50],
                json.dumps(sorted(set(days))),
                only_on.isoformat() if only_on else None,
                position,
                to_utc_iso(clock.now()),
            ),
        )
        row = self.db.one("SELECT * FROM routine_items WHERE id = ?", (item_id,))
        assert row is not None
        return _item(row)

    def find_item(self, member: Member, title: str, routine: Routine | None = None) -> Item | None:
        for each in [routine] if routine else self.of(member):
            found = next((i for i in self.items(each) if title_matches(title, i.title)), None)
            if found is not None:
                return found
        return None

    def remove_item(self, item: Item) -> None:
        self.db.execute("DELETE FROM routine_items WHERE id = ?", (item.id,))

    def tick(self, item: Item, day: date) -> None:
        self.db.execute(
            "INSERT OR IGNORE INTO routine_ticks (item_id, day, ticked_at) VALUES (?, ?, ?)",
            (item.id, day.isoformat(), to_utc_iso(clock.now())),
        )

    async def tick_now(self, item: Item, day: date) -> None:
        """A tick made in Themi (a button, chat), passed on to whoever listens."""
        self.tick(item, day)
        for listener in self.tick_listeners:
            try:
                await listener(item, day)
            except Exception:
                log.warning("A routine tick listener failed for item %s", item.id, exc_info=True)

    def ticked(self, item: Item, day: date) -> bool:
        return bool(
            self.db.one(
                "SELECT 1 FROM routine_ticks WHERE item_id = ? AND day = ?",
                (item.id, day.isoformat()),
            )
        )

    def today_items(self, routine: Routine, day: date) -> list[Item]:
        return [i for i in self.items(routine) if i.applies(day)]

    async def _execute_add(self, payload: dict[str, Any], ctx: ExecutionContext) -> str:
        member = self.store.get_member(int(payload["member"]))
        routine = self.find(member, str(payload["routine"]))
        if routine is None:
            return f"{member.name} has no {payload['routine']} routine any more."
        only = date.fromisoformat(payload["only_on"]) if payload.get("only_on") else None
        item = self.add_item(routine, str(payload["title"]), tuple(payload["days"]), only)
        return f"Added {item.title} to {member.name}'s {routine.name} routine, {item.when()}."

    # ----- the check --------------------------------------------------------------------

    async def check(self) -> int:
        """Scheduler job: each routine whose window has ended today gets its check, once.
        Returns how many messages were sent."""
        tz = self._tz()
        now = clock.now().astimezone(tz)
        sent = 0
        for member in self.store.list_members():
            if member.telegram_user_id is None:
                continue
            for routine in self.of(member):
                end = self._end(routine, member, now)
                if not end <= now < end + CHECK_LATE:
                    continue
                today = now.date()
                if self.db.one(
                    "SELECT 1 FROM routine_day_checks WHERE routine_id = ? AND day = ?",
                    (routine.id, today.isoformat()),
                ):
                    continue
                self.db.execute(
                    "INSERT INTO routine_day_checks (routine_id, day) VALUES (?, ?)",
                    (routine.id, today.isoformat()),
                )
                items = self.today_items(routine, today)
                if not items:
                    continue
                still = [i for i in items if not self.ticked(i, today)]
                words = (
                    "done" if not still else f"not finished ({and_list([i.title for i in still])})"
                )
                self.services.energy.record(
                    member,
                    "device_activity",
                    ROUTINE_SIGNAL if not still else -ROUTINE_SIGNAL,
                    f"{routine.name.lower()} routine {words}",
                )
                if not still:
                    continue
                await self.services.outbox.send(
                    member,
                    CHECK_TEXT.format(part=routine.name, items=_bullets(still)),
                    priority=Priority.NORMAL,
                    kind=KIND,
                    buttons=_buttons(routine, still, today),
                    deadline=end + timedelta(minutes=15),
                    dedupe_key=f"routine-r{routine.id}-{today}",
                    expires=end + CHECK_LATE,
                )
                sent += 1
        return sent

    async def on_button(self, event: InboundEvent) -> None:
        assert event.button is not None
        payload = event.button.payload
        routine = self.db.one(
            "SELECT * FROM routines WHERE id = ? AND member_id = ?",
            (int(payload["routine"]), event.member.id),
        )
        message = event.button.message_id
        if routine is None:
            return
        found = _routine(routine)
        day = date.fromisoformat(str(payload["day"]))
        if payload.get("skip"):
            if message is not None:
                await self.services.outbox.edit(
                    event.member, message, SKIPPED_TEXT.format(part=found.name)
                )
            return
        item = next((i for i in self.items(found) if i.id == int(payload["item"])), None)
        if item is not None:
            await self.tick_now(item, day)
        still = [i for i in self.today_items(found, day) if not self.ticked(i, day)]
        if message is None:
            return
        if still:
            await self.services.outbox.edit(
                event.member,
                message,
                CHECK_TEXT.format(part=found.name, items=_bullets(still)),
                _buttons(found, still, day),
            )
        else:
            await self.services.outbox.edit(
                event.member, message, ALL_DONE_TEXT.format(part=found.name)
            )

    # ----- small things -------------------------------------------------------------------

    def describe(self, member: Member) -> str:
        today = self.today()
        lines = []
        for routine in self.of(member):
            items = [
                f"{i.title}{' (done today)' if self.ticked(i, today) else ''}"
                + ("" if i.applies(today) else f" ({i.when()})")
                for i in self.items(routine)
            ]
            listed = ", ".join(items) if items else "nothing on it yet"
            lines.append(f"{routine.name} ({self.window(routine, member)}): {listed}.")
        return f"{member.name}'s routines in Themi: " + " ".join(lines)

    def _end(self, routine: Routine, member: Member, now: datetime) -> datetime:
        if routine.ends is not None:
            return now.replace(
                hour=routine.ends.hour, minute=routine.ends.minute, second=0, microsecond=0
            )
        at = member.quiet_start
        quiet = now.replace(hour=at.hour, minute=at.minute, second=0, microsecond=0)
        if at < time(12):
            quiet += timedelta(days=1)
        return quiet - EVENING_BEFORE_QUIET

    def today(self) -> date:
        return clock.now().astimezone(self._tz()).date()

    def _tz(self) -> ZoneInfo:
        family = self.store.get_family()
        return ZoneInfo(family.timezone if family else "UTC")


def _bullets(items: list[Item]) -> str:
    return "\n".join(f"- {i.title}" for i in items)


def _buttons(routine: Routine, still: list[Item], day: date) -> list[Button]:
    ticks = [
        Button(
            f"✓ {i.title}"[:40],
            "routine_item",
            {"routine": routine.id, "item": i.id, "day": day.isoformat()},
        )
        for i in still
    ]
    skip = Button(
        "Skip today", "routine_item", {"routine": routine.id, "skip": 1, "day": day.isoformat()}
    )
    return [*ticks, skip]


# ----- chat ---------------------------------------------------------------------------------


def _routines(ctx: ToolContext) -> Routines:
    if ctx.services.routines is None:
        raise ToolFailed("Routines aren't set up.")
    return ctx.services.routines


def _time(text: str, what: str) -> time:
    try:
        return time.fromisoformat(text.strip())
    except ValueError as exc:
        raise ToolFailed(f"{what} is a time like 07:30.") from exc


def _days(names: list[Any]) -> tuple[int, ...]:
    days = []
    for name in names:
        match = [i for i, d in enumerate(DAY_NAMES) if d.lower().startswith(str(name).lower()[:3])]
        if not match:
            raise ToolFailed(f"{name} isn't a day of the week.")
        days.append(match[0])
    return tuple(sorted(set(days)))


ROUTINE_ARG = {"type": "string", "description": "The routine's name, e.g. 'Morning'."}


@tool(
    "show_routines",
    "Read this person's routines kept in Themi: each routine's name and window, and its "
    "items (which are done today). Themi checks each one as its window ends. Not the "
    "Cozyla wall's routines (show_routine).",
    {},
)
async def show_routines(ctx: ToolContext, args: dict[str, Any]) -> str:
    return _routines(ctx).describe(ctx.member) + " Say it in words, as a short list."


@tool(
    "set_routine",
    "Add one of this person's routines in Themi, or change its window or name ('add a "
    "Before school routine from 7 to 8', 'my evening routine ends at 9'). starts and ends: "
    "24-hour times like 07:00; ends '' for until an hour before their quiet hours.",
    {
        "name": ROUTINE_ARG,
        "starts": {"type": "string"},
        "ends": {"type": "string"},
        "new_name": {"type": "string", "description": "A new name, or ''."},
    },
)
async def set_routine(ctx: ToolContext, args: dict[str, Any]) -> str:
    routines = _routines(ctx)
    name = " ".join(str(args["name"]).split()).removesuffix(" routine").strip()
    if not name:
        raise ToolFailed("A routine needs a name.")
    starts = _time(str(args["starts"]), "starts")
    ends = _time(str(args["ends"]), "ends") if str(args.get("ends") or "").strip() else None
    try:
        routine, new = routines.set(ctx.member, name, starts, ends, str(args.get("new_name") or ""))
    except ValueError as exc:
        raise ToolFailed(str(exc)) from exc
    verb = "Added" if new else "Changed"
    return f"{verb} the {routine.name} routine: {routines.window(routine, ctx.member)}."


@tool(
    "remove_routine",
    "Remove one of this person's routines in Themi, with its items.",
    {"name": ROUTINE_ARG},
)
async def remove_routine(ctx: ToolContext, args: dict[str, Any]) -> str:
    routines = _routines(ctx)
    routine = routines.find(ctx.member, str(args["name"]))
    if routine is None:
        raise ToolFailed(f"They have no routine called {args['name']}.")
    count = len(routines.items(routine))
    routines.remove(routine)
    return f"Removed the {routine.name} routine{f' and its {count} items' if count else ''}."


@staged_tool(
    "add_routine_item",
    "Add an item to a routine kept in Themi, theirs or someone else's ('add vitamins to my "
    "morning routine', 'put feed the birds on Michael's evening routine on weekdays'). "
    "days: day names, [] for every day. just_today: true for today only. person: '' for "
    "them. Not the Cozyla wall's routines (add_to_wall_routine), a chore or a list.",
    {
        "routine": ROUTINE_ARG,
        "title": {"type": "string"},
        "days": {"type": "array", "items": {"type": "string", "enum": list(DAY_NAMES)}},
        "just_today": {"type": "boolean"},
        "person": {"type": "string"},
    },
)
async def add_routine_item(ctx: ToolContext, args: dict[str, Any]) -> Proposal:
    routines = _routines(ctx)
    person = str(args.get("person") or "").strip()
    member = ctx.member
    if person:
        found = next(
            (m for m in ctx.services.store.list_members() if name_key(m.name) == name_key(person)),
            None,
        )
        if found is None:
            raise ToolFailed(f"There's nobody called {person} in the family.")
        member = found
    routine = routines.find(member, str(args["routine"]))
    if routine is None:
        raise ToolFailed(
            f"{member.name} has no routine called {args['routine']}; set_routine adds one."
        )
    title = " ".join(str(args["title"]).split())[:50]
    if not title:
        raise ToolFailed("An item needs a name.")
    days = _days(list(args.get("days") or []))
    only_on = routines.today() if args.get("just_today") else None
    said = name_key(ctx.request_text)
    asked = member.id == ctx.member.id and all(
        w in said for w in name_key(title).split() if len(w) > 2
    )
    when = (
        "just today"
        if only_on
        else ("every day" if not days else and_list([DAY_NAMES[d] for d in days]))
    )
    whose = "your" if member.id == ctx.member.id else f"{member.name}'s"
    return Proposal(
        ADD_CATEGORY,
        f"{title} on {whose} {routine.name} routine, {when}",
        ADD_EXECUTOR,
        {
            "member": member.id,
            "routine": routine.name,
            "title": title,
            "days": list(days),
            "only_on": only_on.isoformat() if only_on else None,
        },
        requested=asked,
    )


@tool(
    "remove_routine_item",
    "Remove an item from one of this person's routines in Themi. routine: '' to look in all.",
    {"title": {"type": "string"}, "routine": {"type": "string"}},
)
async def remove_routine_item(ctx: ToolContext, args: dict[str, Any]) -> str:
    routines = _routines(ctx)
    routine = routines.find(ctx.member, str(args["routine"])) if args.get("routine") else None
    item = routines.find_item(ctx.member, str(args["title"]), routine)
    if item is None:
        raise ToolFailed(f"No item like {args['title']} on their routines.")
    routines.remove_item(item)
    return f"Removed {item.title}."


@tool(
    "tick_routine_item",
    "Tick off an item on this person's routine in Themi for today, when they say they did it "
    "('I walked the dog', 'took my vitamins').",
    {"title": {"type": "string"}},
)
async def tick_routine_item(ctx: ToolContext, args: dict[str, Any]) -> str:
    routines = _routines(ctx)
    item = routines.find_item(ctx.member, str(args["title"]))
    if item is None:
        raise ToolFailed(f"No item like {args['title']} on their routines.")
    await routines.tick_now(item, routines.today())
    return f"Ticked {item.title} for today."
