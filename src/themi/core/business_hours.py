"""A call before the business closes (F34k, Erin's idea #177).

"For tasks that are clearly linked to a specific company's business hours (eg. calling the
dentist or a restaurant), Themi should note the business hours and send an extra prompt 1-2
hours before the business closes for the day ... call now, later (voicemail ok), or later
(next business day)."

A call task whose title names a business ("Call the dentist", "Phone Rosewood Dental about
the bill"; not "Call mom") gets that place's hours looked up once, by the hourly job: a
place's hours said in chat or found before come first, else one near-home web search (F31c),
read by `parse_hours` here, with no model call. They're kept by place (`place_hours`), so a
correction is remembered for the next call to it. Not found: the task says so once.

On a day it's open, and the task is due or open: one extra nudge an hour and a half before
closing, through the outbox like every message (quiet hours, the daily limit, gentle
phrasing): "Rosewood Dental closes at 5 today. Call now, or later?" [Call now] [Later,
voicemail's fine] [Next open day]. Not on a day it's closed.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from themi import clock
from themi.accounts import Member
from themi.channels.events import Button, InboundEvent
from themi.channels.outbox import Priority
from themi.core.lists import name_key
from themi.core.tasks import NotFound, Task, TaskBoard, clock_words
from themi.core.tools import ToolContext, ToolFailed, tool
from themi.localtime import member_day, to_utc_iso
from themi.modules import Module, ModuleContext

if TYPE_CHECKING:
    from themi.core.services import Services

log = logging.getLogger(__name__)

KIND = "closing"
BEFORE_CLOSE = timedelta(minutes=90)
LATEST = timedelta(minutes=30)  # no nudge once closing is this near
DAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")

NUDGE_TEXT = "{name} closes at {close} today. Call now, or later?"
UNKNOWN_TEXT = (
    'I couldn\'t find {name}\'s hours, so there\'s no "before they close" reminder for "{title}".'
)
LATER_TEXT = "Later, then: after {close}, voicemail's fine."
NEXT_DAY_TEXT = "Next open day, then: {day} after {at}."
CALL_TEXT = "{name}{number}."
SAID = "said in chat"

CALL = re.compile(
    r"^\s*(?:call|phone|ring|telephone|visit)\s+(?:up\s+)?(?:the\s+)?(.+?)"
    r"(?:\s+(?:about|to|for|re|regarding|and|after|before|on|at)\b.*)?\s*$",
    re.IGNORECASE,
)
PEOPLE = re.compile(
    r"\b(?:mom|mum|mommy|dad|daddy|mother|father|grandma|grandpa|granny|nana|papa|aunt\w*|"
    r"uncle|sister|brother|sis|bro|cousin|wife|husband|partner|friend|son|daughter|kids?|"
    r"back|them|him|her|someone|somebody)\b",
    re.IGNORECASE,
)
BUSINESS = re.compile(
    r"\b(?:dentist|dental|doctor|dr|clinic|office|pharmacy|vet|veterinar\w*|bank|store|shop|"
    r"restaurant|cafe|salon|barber|garage|mechanic|insurance|company|school|hospital|dmv|"
    r"library|post office|plumber|electrician|repair|service|center|centre|optometrist|"
    r"orthodontist|pediatrician|therapist|daycare|gym|studio|agency|bakery|hardware|"
    r"cleaners|utility|county|city hall|landlord|leasing)\b",
    re.IGNORECASE,
)


def business_in(task: Task) -> str | None:
    """The place a call task is for ("the dentist", "Rosewood Dental"), or None."""
    if task.kind != "call" and not CALL.match(task.title):
        return None
    m = CALL.match(task.title)
    name = (m.group(1) if m else task.title).strip(" .!?")
    if not name or PEOPLE.search(name):
        return None
    capitals = sum(1 for w in name.split() if w[:1].isupper())
    if BUSINESS.search(name) or capitals >= 2:
        return name
    return None


# ----- reading hours -----------------------------------------------------------------------

_DAY = r"(?:mon|tue|wed|thu|fri|sat|sun)[a-z]*\.?"
_RANGE = rf"{_DAY}(?:\s*(?:-|to|through|thru)\s*{_DAY})?"
_SPEC = (
    rf"(?:{_RANGE}(?:\s*(?:,|&|and)\s*{_RANGE})*|weekdays|weekends|daily|every\s+day|"
    r"7\s+days(?:\s+a\s+week)?)"
)
_TIME = r"(\d{1,2})(?::(\d{2}))?\s*([ap]\.?m\.?)?"
ENTRY = re.compile(
    rf"({_SPEC})\s*:?\s*(?:(closed)|{_TIME}\s*(?:-|to|until)\s*{_TIME}|(24\s*hours|open\s+24))",
    re.IGNORECASE,
)
DAY_INDEX = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}

Hours = dict[int, tuple[time, time] | None]


def _days(spec: str) -> list[int]:
    spec = spec.lower().strip()
    if spec.startswith(("daily", "every", "7")):
        return list(range(7))
    if spec == "weekdays":
        return [0, 1, 2, 3, 4]
    if spec == "weekends":
        return [5, 6]
    out: list[int] = []
    for part in re.split(r"\s*(?:,|&|and)\s*", spec):
        ends = re.split(r"\s*(?:-|to|through|thru)\s*", part)
        first, last = DAY_INDEX.get(ends[0][:3]), DAY_INDEX.get(ends[-1][:3])
        if first is None or last is None:
            continue
        n = first
        while True:
            out.append(n)
            if n == last:
                break
            n = (n + 1) % 7
    return out


def _clock(hour: str, minute: str | None, half: str | None) -> tuple[int, int, str]:
    return int(hour), int(minute or 0), (half or "").lower()[:1]


def _span(m: re.Match[str]) -> tuple[time, time] | None:
    oh, om, oa = _clock(m.group(3), m.group(4), m.group(5))
    ch, cm, ca = _clock(m.group(6), m.group(7), m.group(8))
    if not (0 < oh <= 24 and 0 < ch <= 24 and om < 60 and cm < 60):
        return None
    opens = oh % 12 + (12 if oa == "p" else 0) if oa else (oh if oh != 12 else 12)
    closes = ch % 12 + (12 if ca == "p" else 0) if ca else ch
    if not ca and closes <= opens:
        closes += 12  # "8-5": until 5 pm
    if not oa and opens > closes:
        opens -= 12
    if not 0 <= opens < closes <= 24:
        return None
    end = time(23, 59) if closes == 24 else time(closes, cm)
    return time(opens, om), end


def parse_hours(text: str) -> Hours:
    """Opening hours in a web snippet or their words: "Mon-Fri 8am-5pm, Sat 9-1, Sun
    closed". Days not mentioned are closed, once any day is read. {} when none are."""
    cleaned = re.sub("[\u2013\u2014\u2012]", "-", text)
    found: Hours = {}
    for m in ENTRY.finditer(cleaned):
        days = _days(m.group(1))
        if m.group(2):
            span = None
        elif m.group(9):
            span = (time(0), time(23, 59))
        else:
            span = _span(m)
            if span is None:
                continue
        for day in days:
            found.setdefault(day, span)
    if not found:
        return {}
    return {day: found.get(day) for day in range(7)}


def hours_json(hours: Hours) -> str:
    return json.dumps(
        {str(d): [s[0].strftime("%H:%M"), s[1].strftime("%H:%M")] if s else None
         for d, s in hours.items()}
    )  # fmt: skip


def hours_from_json(raw: str) -> Hours:
    data = json.loads(raw)
    return {
        int(d): (time.fromisoformat(s[0]), time.fromisoformat(s[1])) if s else None
        for d, s in data.items()
    }


def read_back(hours: Hours) -> str:
    """ "Monday to Friday 8 am-5 pm; Saturday 9 am-1 pm; closed Sunday"."""
    groups: list[tuple[list[int], tuple[time, time] | None]] = []
    for day in range(7):
        span = hours.get(day)
        if groups and groups[-1][1] == span:
            groups[-1][0].append(day)
        else:
            groups.append(([day], span))
    parts = []
    for days, span in groups:
        named = DAY_NAMES[days[0]] + (f" to {DAY_NAMES[days[-1]]}" if len(days) > 1 else "")
        parts.append(
            f"{named} {clock_words(span[0])}-{clock_words(span[1])}" if span else f"closed {named}"
        )
    return "; ".join(parts)


PHONE = re.compile(r"(?<!\d)(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}(?!\d)")


# ----- the job and the nudge ----------------------------------------------------------------


class BusinessHours:
    def __init__(self, services: Services, board: TaskBoard) -> None:
        self.services = services
        self.board = board
        self.db = services.store.db

    def install(self) -> None:
        s = self.services
        s.business_hours = self
        s.button_handlers[KIND] = self.on_button
        s.tools.register(set_business_hours)
        self.board.wall_notes.append(self.note)

    def _tz(self) -> ZoneInfo:
        family = self.services.store.get_family()
        return ZoneInfo(family.timezone if family else "UTC")

    def place(self, task: Task) -> dict[str, Any] | None:
        row = self.db.one(
            "SELECT p.* FROM task_places t JOIN place_hours p ON p.place_key = t.place_key "
            "WHERE t.task_id = ?",
            (task.id,),
        )
        return dict(row) if row else None

    def hours(self, task: Task) -> Hours | None:
        place = self.place(task)
        return hours_from_json(place["hours"]) if place and place["hours"] else None

    def note(self, task: Task) -> str | None:
        """For Themi's open items: "Rosewood Dental: open until 5 pm today"."""
        place = self.place(task)
        if place is None:
            return None
        if not place["hours"]:
            return f"{place['name']}'s hours weren't found."
        today = clock.now().astimezone(self._tz()).date()
        span = hours_from_json(place["hours"]).get(today.weekday())
        when = f"open until {clock_words(span[1])} today" if span else "closed today"
        return f"{place['name']}: {when} ({read_back(hours_from_json(place['hours']))})."

    async def look_up(self) -> int:
        """Scheduler job: open call tasks naming a business get its hours, once. Returns how
        many were looked up."""
        looked = 0
        for row in self.db.query(
            "SELECT t.id FROM tasks t LEFT JOIN task_places p ON p.task_id = t.id "
            "WHERE t.status IN ('open', 'snoozed') AND p.task_id IS NULL"
        ):
            task = self.board.get(row["id"])
            name = business_in(task)
            if name is None:
                continue
            key = name_key(name)
            if self.db.one("SELECT 1 FROM place_hours WHERE place_key = ?", (key,)) is None:
                found = await self._search(task, name)
                if found is None:
                    continue  # no search set up, or it failed: tried again next time
                hours, phone, source, shown = found
                self._keep(key, shown, hours, phone, source)
                looked += 1
            self.db.execute(
                "INSERT INTO task_places (task_id, place_key) VALUES (?, ?)", (task.id, key)
            )
            await self._unknown(task)
        return looked

    def _keep(self, key: str, name: str, hours: Hours | None, phone: str, source: str) -> None:
        self.db.execute(
            "INSERT INTO place_hours (place_key, name, hours, phone, source, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(place_key) DO UPDATE SET hours = "
            "excluded.hours, phone = CASE WHEN excluded.phone != '' THEN excluded.phone ELSE "
            "phone END, source = excluded.source, updated_at = excluded.updated_at",
            (key, name, hours_json(hours) if hours else None, phone, source,
             to_utc_iso(clock.now())),
        )  # fmt: skip

    async def _search(self, task: Task, name: str) -> tuple[Hours | None, str, str, str] | None:
        """(hours, phone, link, the place's own name) from one search, or None when there's
        no search to do."""
        from themi.core.web_search import near_home

        search = self.services.web_search
        if search is None or search.backend is None:
            return None
        member_id = task.assignee or task.created_by or 0
        area = search.home_area()
        query = f"{name} hours" if area is None else near_home(f"{name} hours", area)
        try:
            backend = search._ready()
            results = await search._search(backend, member_id, query, deep=False)
        except Exception as exc:  # the cap, or the service: no hours this time
            log.info("No hours lookup for task %s (%s)", task.id, type(exc).__name__)
            return None
        for result in results:  # web text is data: only hours and a number are read from it
            hours = parse_hours(f"{result.title}\n{result.snippet}")
            if hours:
                phone = PHONE.search(result.snippet)
                shown = re.split(r"\s+[|\-\u2013:]\s+", result.title)[0].strip()[:60] or name
                return hours, phone.group(0) if phone else "", result.url, shown
        return None, "", "", name

    async def _unknown(self, task: Task) -> None:
        place = self.place(task)
        if place is None or place["hours"]:
            return
        told = self.db.scalar("SELECT told_unknown FROM task_places WHERE task_id = ?", (task.id,))
        doer = self._doer(task)
        if told or doer is None:
            return
        self.db.execute("UPDATE task_places SET told_unknown = 1 WHERE task_id = ?", (task.id,))
        await self.services.outbox.send(
            doer, UNKNOWN_TEXT.format(name=place["name"], title=task.title),
            priority=Priority.NORMAL, kind="task",
        )  # fmt: skip

    def _doer(self, task: Task) -> Member | None:
        member_id = task.assignee or task.created_by
        return self.services.store.get_member(member_id) if member_id else None

    async def check(self) -> int:
        """Scheduler job (every 15 minutes): the closing-time nudge, once a day per task.
        Returns how many went out."""
        await self.look_up()
        sent = 0
        tz = self._tz()
        now = clock.now()
        for row in self.db.query(
            "SELECT t.task_id FROM task_places t JOIN place_hours p ON p.place_key = t.place_key "
            "JOIN tasks k ON k.id = t.task_id WHERE p.hours IS NOT NULL AND k.status = 'open'"
        ):
            task = self.board.get(row["task_id"])
            doer = self._doer(task)
            hours = self.hours(task)
            if doer is None or hours is None:
                continue
            today = member_day(doer, now, tz)
            if task.due_on is not None and task.due_on > today:
                continue  # not due yet
            if self.board.put_off_until(task, doer) is not None:
                continue
            span = hours.get(now.astimezone(tz).weekday())
            if span is None:
                continue  # closed today
            local = now.astimezone(tz).date()
            close = _at(local, span[1], tz)
            if not close - BEFORE_CLOSE <= now < close - LATEST:
                continue
            if self.db.one(
                "SELECT 1 FROM closing_nudges WHERE task_id = ? AND day = ?",
                (task.id, local.isoformat()),
            ):
                continue
            goes_out = self.services.outbox.send_time(
                doer, Priority.NORMAL, deadline=close - LATEST, kind="task"
            )
            if goes_out >= close - LATEST:
                continue  # quiet hours or the day's limit: too late to be of use today
            self.db.execute(
                "INSERT INTO closing_nudges (task_id, day) VALUES (?, ?)",
                (task.id, local.isoformat()),
            )
            place = self.place(task)
            assert place is not None
            tap = {"task": task.id}
            await self.services.outbox.send(
                doer, NUDGE_TEXT.format(name=place["name"], close=clock_words(span[1])),
                priority=Priority.NORMAL, kind="task", deadline=close - LATEST,
                buttons=[
                    Button("Call now", KIND, {**tap, "action": "now"}),
                    Button("Later, voicemail's fine", KIND, {**tap, "action": "later"}),
                    Button("Next open day", KIND, {**tap, "action": "next_day"}),
                ],
            )  # fmt: skip
            sent += 1
        return sent

    async def on_button(self, event: InboundEvent) -> None:
        assert event.button is not None
        payload = event.button.payload
        task = self.board.get(int(payload["task"]))
        member = event.member
        hours, place = self.hours(task), self.place(task)
        if hours is None or place is None:
            return
        tz = self._tz()
        now = clock.now().astimezone(tz)
        action = payload.get("action")
        if action == "now":
            steps = self.board._steps_for(task, member)
            number = f": {place['phone']}" if place["phone"] else ""
            text = CALL_TEXT.format(name=place["name"], number=number)
            text = f"{text}\n\n{steps}" if steps else text
        elif action == "later":
            span = hours.get(now.weekday())
            close = _at(now.date(), span[1] if span else now.time(), tz)
            until = max(close, now) + timedelta(minutes=5)
            self.board.snooze(task.id, until=until, by=member)
            text = LATER_TEXT.format(close=clock_words(close.time()))
        else:
            day, opens = next_open(hours, now.date())
            if day is None or opens is None:
                return
            at = _at(day, opens, tz) + timedelta(hours=1)
            self.board.snooze(task.id, until=at, by=member)
            text = NEXT_DAY_TEXT.format(day=f"{day:%A}", at=clock_words(at.time()))
        if event.button.message_id is not None:
            await self.services.outbox.edit(member, event.button.message_id, text, ())

    def correct(self, task: Task, said: str) -> str:
        """Their own words for the hours ("Mon-Thu 8-5, Fri 8-noon"), kept for the place."""
        name = business_in(task)
        if name is None:
            raise ValueError("that task isn't a call to a business")
        hours = parse_hours(said.replace("noon", "12pm"))
        if not hours:
            raise ValueError(
                "those hours couldn't be read; try 'Mon-Fri 8am-5pm, Sat 9am-1pm, Sun closed'"
            )
        key = name_key(name)
        known = self.db.scalar("SELECT name FROM place_hours WHERE place_key = ?", (key,))
        self._keep(key, str(known or name), hours, "", SAID)
        self.db.execute(
            "INSERT INTO task_places (task_id, place_key) VALUES (?, ?) "
            "ON CONFLICT(task_id) DO UPDATE SET place_key = excluded.place_key",
            (task.id, key),
        )
        return f"Kept for {known or name}: {read_back(hours)}."


def _at(day: date, at: time, tz: ZoneInfo) -> datetime:
    return datetime(day.year, day.month, day.day, at.hour, at.minute, tzinfo=tz)


def next_open(hours: Hours, after: date) -> tuple[date | None, time | None]:
    for n in range(1, 8):
        day = after + timedelta(days=n)
        span = hours.get(day.weekday())
        if span is not None:
            return day, span[0]
    return None, None


@tool(
    "set_business_hours",
    "Their own words for a business's opening hours, for a call task to it, when they say "
    "Themi has them wrong or tell Themi ('the dentist is open Mon-Thu 8-5, Fri 8-noon'). "
    "Kept for that place for next time. hours: their words, days and times.",
    {"task_id": {"type": "integer"}, "hours": {"type": "string"}},
)
async def set_business_hours(ctx: ToolContext, args: dict[str, Any]) -> str:
    found = ctx.services.business_hours
    if found is None:
        raise ToolFailed("Business hours aren't set up.")
    try:
        task = found.board.get(int(args["task_id"]))
        return found.correct(task, str(args["hours"]))
    except NotFound as exc:
        raise ToolFailed("There's no task with that number.") from exc
    except ValueError as exc:
        raise ToolFailed(f"Not kept: {exc}.") from exc


class BusinessHoursModule(Module):
    """F34k: errands that need a place to be open."""

    name = "business_hours"
    requires = ("tasks",)

    def install(self, ctx: ModuleContext) -> None:
        hours = ctx.provide(BusinessHours(ctx.services, ctx.get(TaskBoard)))
        hours.install()
        ctx.periodic("tasks.closing", timedelta(minutes=15), hours.check)
