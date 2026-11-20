"""What the wall shows (WL2): everything on the home screen, gathered from Themi's own data.

The Themi Wall Plan's "What the family sees". A shared screen guests can see, so:

- Never email, personal lists, energy, praise counts or settings. Tasks set aside from
  shared displays (`off_displays`) and snoozed ones stay off.
- Something not done yesterday is "from yesterday", never "late"; no points, no scores.

Columns: one per person, with the household's shared things in "Together" between them.
A person's column has the routine for the part of the day it is now, their chores due by
today, and the top of their to-do list in the wall's order (F18d: due or overdue first,
important before the rest, then the soonest). Together has chores either of you can do
and the family's to-dos (tasks on both lists).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from themi import clock
from themi.accounts import Member
from themi.core import keys

if TYPE_CHECKING:
    from themi.core.services import Services
    from themi.standard.routines import Routine, Routines
    from themi.standard.tasks import Task

TODOS_SHOWN = 3
FAMILY_TODOS_SHOWN = 5
SMALL_ITEMS = 4
EVENING_BEFORE_QUIET = timedelta(hours=1)  # as routines' own evening (R1a)
IMPORTANCE = {"high": 0, "normal": 1, "low": 2}
TOGETHER = "together"
DAY_STARTS = 8  # the timeline's earliest start, unless an event is earlier
MIN_BLOCK = 1.5  # % of the hours: the narrowest event drawn (a 5-minute one is still seen)
WEEK_EVENTS = 3
TOMORROW_SHOWN = 4


@dataclass(frozen=True)
class WallItem:
    key: str  # "task-12", "step-5-2026-11-19": what a tap (WL4) names
    title: str
    sub: str = ""
    done: bool = False


@dataclass(frozen=True)
class WallSection:
    title: str
    items: tuple[WallItem, ...] = ()
    empty: str = ""  # said when there's nothing ("Nothing set for this evening")
    more: bool = False  # "More on the list"


@dataclass(frozen=True)
class WallColumn:
    key: str  # "m3", or "together"
    name: str
    initial: str
    tone: str  # the colour's class: "p0", "p1", ... or "family"
    summary: str
    sections: tuple[WallSection, ...]
    member_id: int | None = None


@dataclass(frozen=True)
class WallWeather:
    icon: str  # a data URI
    high: str  # "54°"
    low: str
    alert: str = ""  # an NWS alert in force ("Winter Storm Warning")


@dataclass(frozen=True)
class SmallList:
    name: str
    items: tuple[str, ...]
    more: int = 0


@dataclass(frozen=True)
class WallEvent:
    """One event as the wall shows it: its row ("m3", or "family"), its colour's class, and
    its title ("Busy" for someone who keeps their calendar's details to themselves)."""

    row: str
    tone: str
    title: str
    start: datetime  # local
    end: datetime
    all_day: bool = False


@dataclass(frozen=True)
class Block:
    title: str
    when: str  # "6:30-8:30 pm", with an en dash
    x: float  # % along the hours
    width: float
    lane: int  # stacked in its row: this lane of `lanes`
    lanes: int
    past: bool


@dataclass(frozen=True)
class TimelineRow:
    key: str
    name: str
    tone: str
    blocks: tuple[Block, ...]


@dataclass(frozen=True)
class Tick:
    label: str
    x: float


@dataclass(frozen=True)
class Chip:
    title: str
    tone: str


@dataclass(frozen=True)
class TodayLine:
    """Today's timeline (WL3): the day card's rules laid sideways."""

    start: datetime
    end: datetime
    ticks: tuple[Tick, ...]
    rows: tuple[TimelineRow, ...]
    all_day: tuple[Chip, ...]
    now: float  # % along the hours, held inside them
    tomorrow: tuple[Chip, ...]


@dataclass(frozen=True)
class WeekDay:
    weekday: str  # "Fri"
    date: str  # "20"
    events: tuple[Chip, ...]
    more: int = 0


@dataclass(frozen=True)
class WallScreen:
    now: datetime  # local
    weekday: str  # "Thursday, November 19"
    time: str  # "7:42"
    meridiem: str  # "PM"
    weather: WallWeather | None
    note: str | None
    columns: tuple[WallColumn, ...]
    smalls: tuple[SmallList, ...] = field(default=())
    today: TodayLine | None = None  # WL3: None when there's no calendar
    week: tuple[WeekDay, ...] = ()


class WallView:
    def __init__(self, services: Services) -> None:
        self.services = services

    # ----- the whole screen -------------------------------------------------------------

    def screen(self) -> WallScreen:
        now = self.now()
        return WallScreen(
            now=now,
            weekday=f"{now:%A}, {now:%B} {now.day}",
            time=f"{now.hour % 12 or 12}:{now.minute:02d}",
            meridiem="AM" if now.hour < 12 else "PM",
            weather=self.weather(),
            note=self.note(),
            columns=self.columns(),
            smalls=self.smalls(),
            today=self.today_line(),
            week=self.week(),
        )

    def tz(self) -> ZoneInfo:
        family = self.services.store.get_family()
        return ZoneInfo(family.timezone if family else "UTC")

    def now(self) -> datetime:
        return clock.now().astimezone(self.tz())

    def people(self) -> list[Member]:
        return self.services.store.list_members()

    # ----- the columns ------------------------------------------------------------------

    def columns(self) -> tuple[WallColumn, ...]:
        people = self.people()
        today = self.now().date()
        tasks = self._open_tasks(people)
        columns = [self._person(i, m, tasks, today) for i, m in enumerate(people)]
        together = self._together(tasks, today)
        columns.insert(len(columns) // 2 if len(columns) > 1 else len(columns), together)
        return tuple(columns)

    def _open_tasks(self, people: list[Member]) -> list[Task]:
        board = self.services.maybe(keys.taskboard)
        if board is None:
            return []
        seen: dict[int, Task] = {}
        for member in people:
            for task in board.open_for(member):
                if task.status == "open" and not task.off_displays:
                    seen.setdefault(task.id, task)
        return list(seen.values())

    def _person(self, index: int, member: Member, tasks: list[Task], today: date) -> WallColumn:
        sections: list[WallSection] = []
        routine_section = self._routine(member)
        if routine_section is not None:
            sections.append(routine_section)
        mine = [t for t in tasks if t.assignee == member.id and not _for_both(t)]
        chores = sorted(
            (t for t in mine if t.repeats and t.due_on is not None and t.due_on <= today),
            key=lambda t: _rank(t, today),
        )
        sections.append(WallSection("Chores", tuple(self._task_item(t, today) for t in chores)))
        todos = sorted((t for t in mine if not t.repeats), key=lambda t: _rank(t, today))
        sections.append(
            WallSection(
                "To-do",
                tuple(self._task_item(t, today) for t in todos[:TODOS_SHOWN]),
                empty="Nothing on the list",
                more=len(todos) > TODOS_SHOWN,
            )
        )
        done = self._done_today(member)
        return WallColumn(
            key=f"m{member.id}",
            name=member.name,
            initial=member.name[:1].upper(),
            tone=f"p{index % 4}",
            summary=f"{done} done {self._today_word()}" if done else self._part_word(),
            sections=tuple(s for s in sections if s.items or s.empty),
            member_id=member.id,
        )

    def _together(self, tasks: list[Task], today: date) -> WallColumn:
        both = [t for t in tasks if _for_both(t)]
        either = sorted(
            (t for t in both if t.repeats and t.due_on is not None and t.due_on <= today),
            key=lambda t: _rank(t, today),
        )
        family = sorted((t for t in both if not t.repeats), key=lambda t: _rank(t, today))
        return WallColumn(
            key=TOGETHER,
            name="Together",
            initial="",
            tone="family",
            summary=self._part_word(),
            sections=(
                WallSection("Either of you", tuple(self._task_item(t, today) for t in either)),
                WallSection(
                    "Family to-do",
                    tuple(self._task_item(t, today) for t in family[:FAMILY_TODOS_SHOWN]),
                    empty="Nothing on the list",
                    more=len(family) > FAMILY_TODOS_SHOWN,
                ),
            ),
        )

    def _task_item(self, task: Task, today: date) -> WallItem:
        return WallItem(f"task-{task.id}", task.title, since(task.due_on, today))

    def _done_today(self, member: Member) -> int:
        board = self.services.maybe(keys.taskboard)
        routines = self.services.maybe(keys.routines)
        now = self.now()
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        count = len(board.done_between(member, start, now + timedelta(seconds=1))) if board else 0
        if routines is not None:
            day = routines.today(member)
            count += sum(
                1
                for routine in routines.of(member)
                for item in routines.today_items(routine, day)
                if routines.ticked(item, day)
            )
        return count

    # ----- routines ---------------------------------------------------------------------

    def _routine(self, member: Member) -> WallSection | None:
        routines = self.services.maybe(keys.routines)
        if routines is None:
            return None
        routine = current_routine(routines, member, self.now())
        if routine is None:
            return None
        day = routines.today(member)
        items = tuple(
            WallItem(
                f"step-{item.id}-{day.isoformat()}", item.title, done=routines.ticked(item, day)
            )
            for item in routines.today_items(routine, day)
        )
        part = routine.name.lower()
        return WallSection(f"{routine.name} routine", items, empty=f"Nothing set for this {part}")

    def _part_word(self) -> str:
        hour = self.now().hour
        return "This morning" if hour < 12 else "This afternoon" if hour < 17 else "This evening"

    def _today_word(self) -> str:
        return "tonight" if self.now().hour >= 17 else "today"

    # ----- the top: weather and the note --------------------------------------------------

    def weather(self) -> WallWeather | None:
        from themi.drawing.svg import icon
        from themi.standard.day_card import CardHour, day_icon, degrees

        weather = self.services.maybe(keys.weather)
        forecast = weather.latest() if weather is not None else None
        if weather is None or forecast is None:
            return None
        now = self.now()
        today = forecast.day(now.date())
        if today is None:
            return None
        hours = [
            CardHour(h.at, h.temp, h.chance, h.code)
            for h in forecast.hours
            if h.at.astimezone(now.tzinfo).date() == now.date()
        ]
        start = now.replace(hour=7, minute=0, second=0, microsecond=0)
        units = weather.settings.units
        alerts = [a for a in weather.latest_alerts() if a.starts <= now and _in_force(a, now)]
        return WallWeather(
            icon=icon(day_icon(hours, start, start.replace(hour=21))),
            high=degrees(today.high, units),
            low=degrees(today.low, units),
            alert=alerts[0].event if alerts else "",
        )

    def note(self) -> str | None:
        """At most one line, worded as an offer (the plan's "Themi's note"): a weather alert
        first, then a chore still open from before today, one either of you can do first."""
        weather = self.services.maybe(keys.weather)
        now = self.now()
        if weather is not None:
            alerts = [a for a in weather.latest_alerts() if a.starts <= now and _in_force(a, now)]
            if alerts:
                alert = alerts[0]
                until = f" until {_clock(alert.ends.astimezone(now.tzinfo))}" if alert.ends else ""
                return f"{alert.event}{until}. Worth a look before heading out."
        today = now.date()
        waiting = sorted(
            (
                t
                for t in self._open_tasks(self.people())
                if t.repeats and t.due_on is not None and t.due_on < today
            ),
            # either of you first: an offer suits a shared screen best
            key=lambda t: (not _for_both(t), IMPORTANCE.get(t.importance, 1), t.due_on, t.id),
        )
        if not waiting:
            return None
        task = waiting[0]
        when = "yesterday" if task.due_on == today - timedelta(days=1) else "earlier"
        if _for_both(task):
            return f"{task.title} is still waiting from {when}. Whoever has a moment could do it."
        return f"{task.title} is still waiting from {when}, whenever there's a moment."

    # ----- the calendar: today's timeline and the week ahead (WL3) --------------------------

    def has_calendar(self) -> bool:
        return (
            self.services.maybe(keys.calendars) is not None
            and self.services.maybe(keys.day_summary) is not None
        )

    def events(self, day: date) -> list[WallEvent]:
        """A day's events, each once: a person's own in their row, the family calendar's in
        Family's. Titles only from someone who shares their calendar's details with their
        partner (K1's "partner"); anyone else's events are "Busy". Themi's copies of tasks
        are left out: those are tasks, not plans."""
        from themi.core.calendar_view import CalendarPreferences

        summary = self.services.maybe(keys.day_summary)
        if summary is None or not self.has_calendar():
            return []
        tz = self.tz()
        out: list[WallEvent] = []
        seen: set[tuple[str, str]] = set()
        for index, member in enumerate(self.people()):
            prefs = self.services.store.preferences(member.id, CalendarPreferences)
            shares = prefs.calendar_details == "partner"
            for entry, whose in summary.events(member, day, tasks=False, scope="mine"):
                if entry.event_id and (entry.calendar_id, entry.event_id) in seen:
                    continue
                seen.add((entry.calendar_id, entry.event_id))
                family = bool(whose)  # " (on the Madicen Family calendar)"
                out.append(
                    WallEvent(
                        row="family" if family else f"m{member.id}",
                        tone="family" if family else f"p{index % 4}",
                        title=entry.title if family or shares else "Busy",
                        start=entry.starts_at.astimezone(tz),
                        end=entry.ends_at.astimezone(tz),
                        all_day=entry.all_day,
                    )
                )
        return out

    def today_line(self) -> TodayLine | None:
        if not self.has_calendar():
            return None
        now = self.now()
        rows = [(f"m{m.id}", m.name, f"p{i % 4}") for i, m in enumerate(self.people())]
        rows.append(("family", "Family", "family"))
        tomorrow = self.events(now.date() + timedelta(days=1))
        return lay_out_today(now, rows, self.events(now.date()), tomorrow)

    def week(self) -> tuple[WeekDay, ...]:
        """Seven days from tomorrow, up to three events each."""
        if not self.has_calendar():
            return ()
        first = self.now().date() + timedelta(days=1)
        days = []
        for offset in range(7):
            day = first + timedelta(days=offset)
            events = sorted(self.events(day), key=lambda e: (not e.all_day, e.start))
            chips = tuple(Chip(e.title, e.tone) for e in events)
            days.append(
                WeekDay(
                    f"{day:%a}",
                    str(day.day),
                    chips[:WEEK_EVENTS],
                    max(0, len(chips) - WEEK_EVENTS),
                )
            )
        return tuple(days)

    # ----- the small lists ------------------------------------------------------------

    def smalls(self) -> tuple[SmallList, ...]:
        found: list[SmallList] = []
        groceries = self.services.maybe(keys.groceries)
        if groceries is not None:
            names = [g.name[:1].upper() + g.name[1:] for g in groceries.needed()]
            found.append(_small("Groceries", names))
        lists = self.services.maybe(keys.lists)
        people = self.people()
        if lists is not None and people:
            household = [
                nl
                for nl in lists.visible(people[0])
                if not nl.personal and nl.purpose is None and nl.open_items
            ]
            for nl in household[:2]:
                found.append(_small(nl.name, [i.name for i in nl.open_items]))
        return tuple(found)


# ----- helpers ------------------------------------------------------------------------


def _for_both(task: Task) -> bool:
    return task.shared or task.either


def _rank(task: Task, today: date) -> tuple[int, int, date, int]:
    """The wall's order (F18d): due or overdue first, then important, then the soonest."""
    due = task.due_on or date.max
    return (0 if due <= today else 1, IMPORTANCE.get(task.importance, 1), due, task.id)


def since(due: date | None, today: date) -> str:
    """A gentle word for something not done when it was due: never "late"."""
    if due is None or due >= today:
        return ""
    days = (today - due).days
    if days == 1:
        return "from yesterday"
    if days < 7:
        return f"from {due:%A}"
    return f"since {due:%b} {due.day}"


def current_routine(routines: Routines, member: Member, now: datetime) -> Routine | None:
    """The routine whose window holds `now` (local): the one that started last."""
    at = now.time()
    started = [r for r in routines.of(member) if r.starts <= at < _routine_end(r, member)]
    return max(started, key=lambda r: r.starts, default=None)


def _routine_end(routine: Routine, member: Member) -> time:
    if routine.ends is not None:
        return routine.ends
    end = datetime.combine(date(2000, 1, 1), member.quiet_start) - EVENING_BEFORE_QUIET
    return time(23, 59, 59) if member.quiet_start < time(12) else end.time()


def _in_force(alert: object, now: datetime) -> bool:
    ends = getattr(alert, "ends", None)
    return ends is None or ends > now


def _clock(at: datetime) -> str:
    hour = at.hour % 12 or 12
    minutes = f":{at.minute:02d}" if at.minute else ""
    return f"{hour}{minutes} {'am' if at.hour < 12 else 'pm'}"


def _small(name: str, items: list[str]) -> SmallList:
    return SmallList(name, tuple(items[:SMALL_ITEMS]), max(0, len(items) - SMALL_ITEMS))


def lay_out_today(
    now: datetime,
    rows: list[tuple[str, str, str]],
    events: list[WallEvent],
    tomorrow: list[WallEvent],
) -> TodayLine:
    """Today's events on hours laid sideways, by the day card's rules (`themi.drawing.
    layout`): 8 am to 9 pm, stretched to take in an earlier or later event; a label every
    two hours on a long day; events that overlap stacked in their row."""
    from themi.drawing.layout import Span, Timeline, columns, window
    from themi.standard.day_card import span_words

    timed = [e for e in events if not e.all_day]
    spans = [Span(f"{e.row}:{i}", e.start, e.end) for i, e in enumerate(timed)]
    morning = now.replace(hour=DAY_STARTS, minute=0, second=0, microsecond=0)
    start, end = window(morning, spans)
    line = Timeline(start, end, 0.0, 100.0)
    placed: list[TimelineRow] = []
    for key, name, tone in rows:
        mine = [(span, e) for span, e in zip(spans, timed, strict=True) if e.row == key]
        lanes = columns([span for span, _ in mine])
        blocks = []
        for span, e in sorted(mine, key=lambda pair: pair[1].start):
            x = line.y(e.start)
            lane, count = lanes[span.key]
            blocks.append(
                Block(
                    title=e.title,
                    when=span_words(e.start, e.end),
                    x=round(x, 2),
                    width=round(max(line.y(e.end) - x, MIN_BLOCK), 2),
                    lane=lane,
                    lanes=count,
                    past=e.end <= now,
                )
            )
        placed.append(TimelineRow(key, name, tone, tuple(blocks)))
    return TodayLine(
        start=start,
        end=end,
        ticks=tuple(Tick(t.label, round(t.y, 2)) for t in line.ticks()),
        rows=tuple(placed),
        all_day=tuple(Chip(e.title, e.tone) for e in events if e.all_day),
        now=round(line.y(now), 2),
        tomorrow=tuple(
            Chip(e.title, e.tone)
            for e in sorted(tomorrow, key=lambda e: (not e.all_day, e.start))[:TOMORROW_SHOWN]
        ),
    )
