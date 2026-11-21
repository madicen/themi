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

import re
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING, ClassVar, Literal
from zoneinfo import ZoneInfo

from pydantic import Field, field_validator

from themi import clock
from themi.accounts import Member
from themi.accounts.household import HouseholdSettings
from themi.core import keys
from themi.core.wording import and_list
from themi.localtime import to_utc_iso
from themi_home.wall_columns import TOGETHER, TOGETHER_TONE, Place, WallColumns, key_of

if TYPE_CHECKING:
    from themi.core.services import Services
    from themi.standard.routines import Routine, Routines
    from themi.standard.tasks import Task

TODOS_SHOWN = 3
FAMILY_TODOS_SHOWN = 5
SMALL_ITEMS = 4
EVENING_BEFORE_QUIET = timedelta(hours=1)  # as routines' own evening (R1a)
IMPORTANCE = {"high": 0, "normal": 1, "low": 2}
COOKING = re.compile(r"\bcook", re.IGNORECASE)  # a list of dishes ("Things to cook")
DAY_STARTS = 8  # the timeline's earliest start, unless an event is earlier
EVENING_STARTS = time(17)  # F52b: when nobody has an evening routine, as routines' default

# F52b: the wall's look, as the Wall module's page offers it, and what the page is told:
# "light", "dark", or "auto" (the frame's own dark theme decides, in wall.js).
Look = Literal["Follow the frame", "Light", "Dark", "Dark in the evening"]
THEME_COLOR = {"light": "#e8ece6", "dark": "#111317"}
MIN_BLOCK = 1.5  # % of the hours: the narrowest event drawn (a 5-minute one is still seen)
WEEK_EVENTS = 3
TOMORROW_SHOWN = 4


@dataclass(frozen=True)
class WallItem:
    key: str  # "task-12", "step-5-2026-11-19": what a tap (WL4) names
    title: str
    sub: str = ""
    done: bool = False
    # WL4: a tap ticks it (or unticks it). A chore's round, once done, can't be undone.
    tappable: bool = True
    asking: bool = False  # "Who did it?" is showing under it
    emoji: str = ""  # F55d (idea #245): the item's emoji, as the tasks picture has it


@dataclass(frozen=True)
class WallPerson:
    """Someone a Together item can be ticked for."""

    id: int
    name: str
    tone: str


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
    # WL5b: what a tap opens: "groceries" (its List view), or "dishes" (each item its Dish
    # view, by `ids`), or "" (nothing)
    opens: str = ""
    ids: tuple[int, ...] = ()
    count: int = 0  # WL9b: everything on it, for the card's "2 items" / "4 ideas"
    tone: str = ""  # WL9b: the household's colour, on a card that opens something


@dataclass(frozen=True)
class WallNote:
    text: str
    why: str  # for the Note view
    key: str  # "task-12", "alert-Wind Advisory"
    task_id: int | None = None
    both: bool = False  # a chore either of you can do
    assignee: int | None = None


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
    # WL5a: where it came from, for its view: whose reading, the calendar and the event
    member_id: int = 0
    calendar_id: str = ""
    event_id: str = ""
    place: str = ""  # "" unless its details are shown
    video: bool = False
    notes: str = ""  # WL7: its notes, "" unless its details are shown (the Event view only)

    @property
    def ref(self) -> str:
        """The Event view's query string."""
        from urllib.parse import urlencode

        return urlencode(
            {"day": self.start.date().isoformat(), "m": self.member_id,
             "c": self.calendar_id, "e": self.event_id}
        )  # fmt: skip


@dataclass(frozen=True)
class Block:
    title: str
    when: str  # "6:30-8:30 pm", with an en dash
    x: float  # % along the hours
    width: float
    lane: int  # stacked in its row: this lane of `lanes`
    lanes: int
    past: bool
    ref: str = ""  # WL5a: the Event view's query string


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
    live: bool = True  # WL5a: today's, with a now line (a Day view's other days have none)


@dataclass(frozen=True)
class WeekCalendar:
    """F55f (idea #239): a calendar with an event in the week ahead, as a chip a tap turns
    off there (`off`) and on again."""

    key: str  # its calendar id
    name: str  # "Erin's Work"
    tone: str
    off: bool = False


@dataclass(frozen=True)
class WeekDay:
    weekday: str  # "Fri"
    date: str  # "20"
    iso: str  # WL5a: for its Day view
    events: tuple[Chip, ...]
    more: int = 0


class WallSettings(HouseholdSettings):
    """WL6: when the wall goes quiet for the night. It wakes at the first morning routine.
    WL8: whether Themi's note mentions parcels due today (off for present season).
    F52b: light or dark, or as the frame is set, or dark from the evening routine."""

    module: ClassVar[str] = "wall"
    bedtime: str = "23:00"
    deliveries: bool = True
    look: Look = Field(
        "Follow the frame",
        description="Follow the frame uses the frame's own dark theme. Dark in the evening "
        "goes dark when the evening routine starts and light again at the first morning one.",
    )

    @field_validator("bedtime")
    @classmethod
    def _bedtime(cls, value: str) -> str:
        try:
            hour, minute = (int(part) for part in value.strip().split(":")[:2])
            return f"{time(hour, minute):%H:%M}"
        except ValueError as exc:
            raise ValueError(f"'{value}' isn't a time like 23:00") from exc


@dataclass(frozen=True)
class NightView:
    """WL6: the dim screen from bedtime to the first morning routine."""

    heading: str  # "Tomorrow, Thursday", or "This morning" after midnight
    plan: tuple[Chip, ...]  # the day's first events and morning steps, with whose
    low: str  # "49° tonight", or ""
    line: str  # one reassuring line


@dataclass(frozen=True)
class WallScreen:
    now: datetime  # local
    weekday: str  # "Thursday, November 19"
    time: str  # "7:42"
    meridiem: str  # "PM"
    weather: WallWeather | None
    note: WallNote | None
    columns: tuple[WallColumn, ...]
    smalls: tuple[SmallList, ...] = field(default=())
    today: TodayLine | None = None  # WL3: None when there's no calendar
    week: tuple[WeekDay, ...] = ()
    week_calendars: tuple[WeekCalendar, ...] = ()  # F55f: none with fewer than two
    people: tuple[WallPerson, ...] = ()  # WL4: "Who did it?"
    night: NightView | None = None  # WL6: None by day
    look: str = "light"  # F52b: "light", "dark" or "auto"


class WallView:
    def __init__(self, services: Services) -> None:
        self.services = services
        self._places: list[Place] | None = None
        self._week: list[tuple[date, list[WallEvent]]] | None = None

    # ----- the whole screen -------------------------------------------------------------

    def screen(self, ask: str = "") -> WallScreen:
        """The whole screen; `ask`: the Together item whose "Who did it?" is showing."""
        now = self.now()
        return WallScreen(
            now=now,
            weekday=f"{now:%A}, {now:%B} {now.day}",
            time=f"{now.hour % 12 or 12}:{now.minute:02d}",
            meridiem="AM" if now.hour < 12 else "PM",
            weather=self.weather(),
            note=self.note(),
            columns=self.columns(ask),
            smalls=self.smalls(),
            today=self.today_line(),
            week=self.week(),
            week_calendars=self.week_calendars(),
            people=tuple(WallPerson(m.id, m.name, self.tone_of(m)) for m in self.people()),
            night=self.night(),
            look=self.look(),
        )

    # ----- WL6: the night -------------------------------------------------------------

    def bedtime(self) -> time:
        hour, minute = self.services.store.household(WallSettings).bedtime.split(":")
        return time(int(hour), int(minute))

    def morning(self) -> time:
        """When the wall wakes: the first morning routine anyone has (8 am by default)."""
        routines = self.services.maybe(keys.routines)
        starts = [r.starts for m in self.people() for r in (routines.of(m) if routines else [])]
        return min(starts, default=time(DAY_STARTS))

    def is_night(self) -> bool:
        at, bed, wake = self.now().time(), self.bedtime(), self.morning()
        if bed > wake:  # 11 pm to 8 am, across midnight
            return at >= bed or at < wake
        return bed <= at < wake  # a bedtime after midnight

    # ----- F52b: the look ---------------------------------------------------------------

    def evening(self) -> time:
        """When the evening routine starts: the earliest anyone's is (5 pm by default)."""
        routines = self.services.maybe(keys.routines)
        starts = [
            r.starts
            for m in self.people()
            for r in (routines.of(m) if routines else [])
            if "evening" in r.name.lower()
        ]
        return min(starts, default=EVENING_STARTS)

    def look(self) -> str:
        chosen = self.services.store.household(WallSettings).look
        if chosen == "Light":
            return "light"
        if chosen == "Dark":
            return "dark"
        if chosen == "Dark in the evening":
            at = self.now().time()
            dark = self.is_night() or at >= self.evening() or at < self.morning()
            return "dark" if dark else "light"
        return "auto"

    def night(self) -> NightView | None:
        if not self.is_night():
            return None
        now = self.now()
        after_midnight = now.time() < self.morning()
        day = now.date() if after_midnight else now.date() + timedelta(days=1)
        heading = "This morning" if after_midnight else f"Tomorrow, {day:%A}"
        events = sorted(self.events(day), key=lambda e: (not e.all_day, e.start))
        plan = [Chip(e.title, e.tone) for e in events[:TOMORROW_SHOWN]]
        routines = self.services.maybe(keys.routines)
        for member in self.people():
            if routines is None:
                break
            first = next(iter(routines.of(member)), None)
            if first is None:
                continue
            for item in routines.today_items(first, day)[:2]:
                plan.append(
                    Chip(
                        f"{item.title} · {member.name}, {first.name.lower()}", self.tone_of(member)
                    )
                )
        weather = self.weather()
        left = any(
            not i.done
            for c in self.columns()
            for s in c.sections
            if s.title != "To-do" and s.title != "Family to-do"
            for i in s.items
        )
        line = (
            "A few things from today will still be here in the morning. Nothing needs doing now."
            if left
            else "Nothing needs doing now."
        )
        return NightView(heading, tuple(plan), f"{weather.low} tonight" if weather else "", line)

    def tz(self) -> ZoneInfo:
        family = self.services.store.get_family()
        return ZoneInfo(family.timezone if family else "UTC")

    def now(self) -> datetime:
        return clock.now().astimezone(self.tz())

    def places(self) -> list[Place]:
        """F53: the columns in the wall's order, each with its colour (as chosen on Wall
        frames, else the defaults)."""
        if self._places is None:
            members = self.services.store.list_members()
            self._places = WallColumns(self.services.store.db).layout(members)
        return self._places

    def people(self) -> list[Member]:
        """The household, in the wall's order (F53)."""
        return [p.member for p in self.places() if p.member is not None]

    def together_tone(self) -> str:
        return next((p.tone for p in self.places() if p.member is None), TOGETHER_TONE)

    def timeline_rows(self) -> list[tuple[str, str, str]]:
        """The timeline's rows: each person in the wall's order, then Family."""
        rows = [(key_of(m), m.name, self.tone_of(m)) for m in self.people()]
        return [*rows, ("family", "Family", self.together_tone())]

    def tone_of(self, member: Member) -> str:
        """F53: the colour class a person is drawn in."""
        return next((p.tone for p in self.places() if p.member and p.member.id == member.id), "p0")

    # ----- the columns ------------------------------------------------------------------

    def columns(self, ask: str = "") -> tuple[WallColumn, ...]:
        people = self.people()
        today = self.now().date()
        tasks = self._open_tasks(people)
        done = self._done_tasks(people)
        columns = []
        for place in self.places():
            if place.member is not None:
                columns.append(self._person(place.member, place.tone, tasks, done, today))
                continue
            together = self._together(tasks, done, today, {m.id: m.name for m in people})
            if ask:
                together = _asking(together, ask)
            columns.append(replace(together, tone=place.tone))
        return tuple(columns)

    def find(self, key: str) -> tuple[WallColumn, WallItem] | None:
        """WL4: an item showing on the wall now, and its column. Only what's shown can be
        tapped."""
        for column in self.columns():
            for section in column.sections:
                for item in section.items:
                    if item.key == key:
                        return column, item
        return None

    def _done_tasks(self, people: list[Member]) -> list[tuple[Task, int | None]]:
        """Tasks (or a chore's round) done today, each once, with who did it: they stay on
        the wall, ticked, until the day ends."""
        board = self.services.maybe(keys.taskboard)
        if board is None:
            return []
        now = self.now()
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        seen: dict[int, tuple[Task, int | None]] = {}
        for member in people:
            for done in board.done_between(member, start, now + timedelta(seconds=1)):
                if not done.task.off_displays:
                    seen.setdefault(done.task.id, (done.task, done.by))
        return list(seen.values())

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

    def _person(
        self,
        member: Member,
        tone: str,
        tasks: list[Task],
        done: list[tuple[Task, int | None]],
        today: date,
    ) -> WallColumn:
        sections: list[WallSection] = []
        routine_section = self._routine(member)
        if routine_section is not None:
            sections.append(routine_section)
        mine = [t for t in tasks if t.assignee == member.id and not _for_both(t)]
        chores = sorted(
            (t for t in mine if t.repeats and t.due_on is not None and t.due_on <= today),
            key=lambda t: _rank(t, today),
        )
        todos = sorted((t for t in mine if not t.repeats), key=lambda t: _rank(t, today))
        shown = {t.id for t in chores} | {t.id for t in todos[:TODOS_SHOWN]}
        finished = [
            t for t, _ in done if t.assignee == member.id and not _for_both(t) and t.id not in shown
        ]
        sections.append(
            WallSection(
                "Chores",
                tuple(self._task_item(t, today) for t in chores)
                + tuple(_done_item(t, emoji=self.emoji_of(t)) for t in finished if t.repeats),
            )
        )
        sections.append(
            WallSection(
                "To-do",
                tuple(self._task_item(t, today) for t in todos[:TODOS_SHOWN])
                + tuple(_done_item(t, emoji=self.emoji_of(t)) for t in finished if not t.repeats),
                empty="Nothing on the list",
                more=len(todos) > TODOS_SHOWN,
            )
        )
        count = self._done_today(member)
        return WallColumn(
            key=f"m{member.id}",
            name=member.name,
            initial=member.name[:1].upper(),
            tone=tone,
            summary=f"{count} done {self._today_word()}" if count else self._part_word(),
            sections=tuple(s for s in sections if s.items or s.empty),
            member_id=member.id,
        )

    def _together(
        self,
        tasks: list[Task],
        done: list[tuple[Task, int | None]],
        today: date,
        names: dict[int, str],
    ) -> WallColumn:
        both = [t for t in tasks if _for_both(t)]
        either = sorted(
            (t for t in both if t.repeats and t.due_on is not None and t.due_on <= today),
            key=lambda t: _rank(t, today),
        )
        family = sorted((t for t in both if not t.repeats), key=lambda t: _rank(t, today))
        shown = {t.id for t in either} | {t.id for t in family[:FAMILY_TODOS_SHOWN]}
        finished = [
            (
                t,
                _done_item(t, f"{names[by]} did it" if by in names else "", emoji=self.emoji_of(t)),
            )
            for t, by in done
            if _for_both(t) and t.id not in shown
        ]
        return WallColumn(
            key=TOGETHER,
            name="Together",
            initial="",
            tone="family",
            summary=self._part_word(),
            sections=(
                WallSection(
                    "Either of you",
                    tuple(self._task_item(t, today) for t in either)
                    + tuple(item for t, item in finished if t.repeats),
                ),
                WallSection(
                    "Family to-do",
                    tuple(self._task_item(t, today) for t in family[:FAMILY_TODOS_SHOWN])
                    + tuple(item for t, item in finished if not t.repeats),
                    empty="Nothing on the list",
                    more=len(family) > FAMILY_TODOS_SHOWN,
                ),
            ),
        )

    def _task_item(self, task: Task, today: date) -> WallItem:
        return WallItem(
            f"task-{task.id}", task.title, since(task.due_on, today), emoji=self.emoji_of(task)
        )

    def emoji_of(self, task: Task) -> str:
        """F55d (idea #245): a family-chosen icon's emoji, else the title's fit, as the tasks
        picture (F43b), or none."""
        from themi.drawing.emoji import item_emoji

        board = self.services.maybe(keys.taskboard)
        return item_emoji(task.title, board.icon_of(task) if board is not None else "")

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
        day = routines.today(member)
        routine = current_routine(routines, member, self.now())
        heading = f"{routine.name} routine" if routine is not None else ""
        if routine is None:
            # F55c (bug #244): the one that ended last today stays while a step is open,
            # until the next starts (or the night view takes over).
            routine = last_routine(routines, member, self.now())
            if routine is None or all(
                routines.ticked(item, day) for item in routines.today_items(routine, day)
            ):
                return None
            heading = f"{routine.name} routine, still open"
        items = tuple(
            WallItem(
                f"step-{item.id}-{day.isoformat()}",
                item.title,
                done=routines.ticked(item, day),
                emoji=step_emoji(item.title),
            )
            for item in routines.today_items(routine, day)
        )
        part = routine.name.lower()
        return WallSection(heading, items, empty=f"Nothing set for this {part}")

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

    def note(self) -> WallNote | None:
        """At most one line, worded as an offer (the plan's "Themi's note"): a weather alert
        first, then a parcel that came today (WL8), then a chore still open from before
        today, one either of you can do first, then a parcel due today. One put off from the
        wall ("Later tonight", "Got it") waits until then (WL5b)."""
        weather = self.services.maybe(keys.weather)
        now = self.now()
        quiet = self._quiet()
        if weather is not None:
            for alert in weather.latest_alerts():
                key = f"alert-{alert.event}"
                if alert.starts <= now and _in_force(alert, now) and key not in quiet:
                    until = (
                        f" until {_clock(alert.ends.astimezone(now.tzinfo))}" if alert.ends else ""
                    )
                    return WallNote(
                        f"{alert.event}{until}. Worth a look before heading out.",
                        "The National Weather Service has it in force here now.",
                        key,
                    )
        today = now.date()
        came, due = self._deliveries(today, quiet)
        if came is not None:
            return came
        chore = self._chore_note(today, quiet)
        return chore if chore is not None else due

    def _deliveries(self, today: date, quiet: set[str]) -> tuple[WallNote | None, WallNote | None]:
        """WL8: notes for the parcels that came today and those still due, from shipping
        emails. Only the shop's name: the wall is shared, and a parcel can be a present."""
        deliveries = self.services.maybe(keys.deliveries)
        if deliveries is None or not self.services.store.household(WallSettings).deliveries:
            return None, None
        found = deliveries.on(today)
        came = [d.shop for d in found if d.status == "delivered"]
        due = [d.shop for d in found if d.status != "delivered"]
        notes: list[WallNote | None] = []
        for shops, kind in ((came, "came"), (due, "due")):
            key = f"delivery-{kind}-{today.isoformat()}-{','.join(shops)}"
            if not shops or key in quiet:
                notes.append(None)
                continue
            several = len(shops) > 1
            what = f"{'Deliveries' if several else 'A delivery'} from {and_list(shops)}"
            if kind == "came":
                text = f"{what} came today. {'They' if several else 'It'} may be at the door."
                why = "A shipping email says it was delivered today."
            else:
                text = f"{what} {'are' if several else 'is'} due today."
                why = "A shipping email says it's expected today."
            notes.append(WallNote(text, why, key))
        return notes[0], notes[1]

    def _chore_note(self, today: date, quiet: set[str]) -> WallNote | None:
        waiting = sorted(
            (
                t
                for t in self._open_tasks(self.people())
                if t.repeats
                and t.due_on is not None
                and t.due_on < today
                and f"task-{t.id}" not in quiet
            ),
            # either of you first: an offer suits a shared screen best
            key=lambda t: (not _for_both(t), IMPORTANCE.get(t.importance, 1), t.due_on, t.id),
        )
        if not waiting:
            return None
        task = waiting[0]
        assert task.due_on is not None
        when = "yesterday" if task.due_on == today - timedelta(days=1) else "earlier"
        names = {m.id: m.name for m in self.people()}
        if _for_both(task):
            text = f"{task.title} is still waiting from {when}. Whoever has a moment could do it."
            whose = "either of you"
        else:
            text = f"{task.title} is still waiting from {when}, whenever there's a moment."
            whose = names.get(task.assignee or 0, "")
        why = (
            f"{task.title} was due {when if when == 'yesterday' else f'on {task.due_on:%A}'} "
            f"and is still open ({whose})."
        )
        return WallNote(text, why, f"task-{task.id}", task.id, _for_both(task), task.assignee)

    def _quiet(self) -> set[str]:
        rows = self.services.store.db.query(
            "SELECT note_key FROM wall_note_quiet WHERE until > ?",
            (to_utc_iso(clock.now()),),
        )
        return {r["note_key"] for r in rows}

    def quiet(self, key: str, until: datetime) -> None:
        """WL5b: no note about this until then."""
        self.services.store.db.execute(
            "INSERT OR REPLACE INTO wall_note_quiet (note_key, until) VALUES (?, ?)",
            (key, to_utc_iso(until)),
        )

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
        for member in self.people():
            prefs = self.services.store.preferences(member.id, CalendarPreferences)
            shares = prefs.calendar_details == "partner"
            for entry, whose in summary.events(member, day, tasks=False, scope="mine"):
                if entry.event_id and (entry.calendar_id, entry.event_id) in seen:
                    continue
                seen.add((entry.calendar_id, entry.event_id))
                family = bool(whose)  # " (on the Madicen Family calendar)"
                shown = family or shares
                out.append(
                    WallEvent(
                        row="family" if family else f"m{member.id}",
                        tone=self.together_tone() if family else self.tone_of(member),
                        title=entry.title if shown else "Busy",
                        start=entry.starts_at.astimezone(tz),
                        end=entry.ends_at.astimezone(tz),
                        all_day=entry.all_day,
                        member_id=member.id,
                        calendar_id=entry.calendar_id,
                        event_id=entry.event_id,
                        place=entry.location if shown and not entry.video else "",
                        video=entry.video,
                        notes=entry.notes if shown else "",
                    )
                )
        return out

    def today_line(self) -> TodayLine | None:
        if not self.has_calendar():
            return None
        now = self.now()
        rows = self.timeline_rows()
        tomorrow = self.events(now.date() + timedelta(days=1))
        return lay_out_today(now, rows, self.events(now.date()), tomorrow)

    def _week_events(self) -> list[tuple[date, list[WallEvent]]]:
        """The seven days from tomorrow and each one's events, read once per screen."""
        if self._week is None:
            first = self.now().date() + timedelta(days=1)
            days = [first + timedelta(days=offset) for offset in range(7)]
            self._week = [(day, self.events(day)) for day in days]
        return self._week

    def week(self) -> tuple[WeekDay, ...]:
        """Seven days from tomorrow, up to three events each. F55f: without the calendars
        turned off for the week ahead."""
        if not self.has_calendar():
            return ()
        from themi_home.wall_calendars import WallCalendars

        hidden = WallCalendars(self.services.store.db).hidden()
        days = []
        for day, found in self._week_events():
            shown = [e for e in found if not e.calendar_id or e.calendar_id not in hidden]
            events = sorted(shown, key=lambda e: (not e.all_day, e.start))
            chips = tuple(Chip(e.title, e.tone) for e in events)
            days.append(
                WeekDay(
                    f"{day:%a}",
                    str(day.day),
                    day.isoformat(),
                    chips[:WEEK_EVENTS],
                    max(0, len(chips) - WEEK_EVENTS),
                )
            )
        return tuple(days)

    def week_calendars(self) -> tuple[WeekCalendar, ...]:
        """F55f (idea #239): each calendar with an event in the week ahead, turned off or
        not, in the wall's order of people, then the shared ones. None with fewer than two."""
        if not self.has_calendar():
            return ()
        from themi_home.wall_calendars import WallCalendars, label

        calendars = WallCalendars(self.services.store.db)
        known = calendars.known(self.people())
        hidden = calendars.hidden()
        people = {m.id: m for m in self.people()}
        order = {m.id: i for i, m in enumerate(self.people())}
        found: dict[str, tuple[tuple[int, str], WeekCalendar]] = {}
        for _, events in self._week_events():
            for event in events:
                key = event.calendar_id
                if not key or key in found:
                    continue
                family = event.row == "family"
                this = known.get(key)
                person = people.get(event.member_id)
                name = (
                    this.name
                    if this is not None
                    else label(person.name, "", "")
                    if person is not None
                    else "Family"
                )
                tone = self.together_tone() if family or person is None else self.tone_of(person)
                rank = (len(order) if family else order.get(event.member_id, len(order)), name)
                found[key] = (rank, WeekCalendar(key, name, tone, key in hidden))
        if len(found) < 2:
            return ()
        return tuple(chip for _, chip in sorted(found.values(), key=lambda pair: pair[0]))

    # ----- the small lists ------------------------------------------------------------

    def smalls(self) -> tuple[SmallList, ...]:
        found: list[SmallList] = []
        groceries = self.services.maybe(keys.groceries)
        if groceries is not None:
            names = [g.name[:1].upper() + g.name[1:] for g in groceries.needed()]
            found.append(
                replace(_small("Groceries", names), opens="groceries", tone=self.together_tone())
            )
        lists = self.services.maybe(keys.lists)
        people = self.people()
        if lists is not None and people:
            household = [
                nl
                for nl in lists.visible(people[0])
                if not nl.personal and nl.purpose is None and nl.open_items
            ]
            for nl in household[:2]:
                small = _small(nl.name, [i.name for i in nl.open_items])
                if COOKING.search(nl.name):  # "Things to cook": each one a dish (WL5b)
                    ids = tuple(i.id for i in nl.open_items[:SMALL_ITEMS])
                    small = replace(small, opens="dishes", ids=ids, tone=self.together_tone())
                found.append(small)
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


def last_routine(routines: Routines, member: Member, now: datetime) -> Routine | None:
    """F55c: the routine whose window ended last, earlier today (local)."""
    at = now.time()
    ended = [r for r in routines.of(member) if r.starts <= at and _routine_end(r, member) <= at]
    return max(ended, key=lambda r: _routine_end(r, member), default=None)


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
    return SmallList(
        name, tuple(items[:SMALL_ITEMS]), max(0, len(items) - SMALL_ITEMS), count=len(items)
    )


def lay_out_today(
    now: datetime,
    rows: list[tuple[str, str, str]],
    events: list[WallEvent],
    tomorrow: list[WallEvent],
    *,
    live: bool = True,
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
                    past=live and e.end <= now,
                    ref=e.ref,
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
        live=live,
    )


def _done_item(task: Task, sub: str = "", *, emoji: str = "") -> WallItem:
    """Ticked today: struck through. A one-off can be unticked; a chore's round can't."""
    return WallItem(
        f"task-{task.id}", task.title, sub, done=True, tappable=not task.repeats, emoji=emoji
    )


def step_emoji(title: str) -> str:
    """F55d: a routine step's emoji, from its title only (F43b: the wall keeps an icon per
    routine, not per step)."""
    from themi.drawing.emoji import item_emoji

    return item_emoji(title)


def _asking(column: WallColumn, key: str) -> WallColumn:
    sections = tuple(
        replace(
            section,
            items=tuple(
                replace(i, asking=True) if i.key == key and not i.done else i for i in section.items
            ),
        )
        for section in column.sections
    )
    return replace(column, sections=sections)
