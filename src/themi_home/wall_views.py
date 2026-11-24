"""The wall's views (WL5a): what slides up when something on the home screen is tapped.

The Themi Wall Plan's "Tapping things". One view at a time, one level deep:

- Event: whose calendar, the time, how long until it starts or how long is left, where (only
  when its details are shown at all: WL3's Busy rule holds), when to leave (the travel
  lead-in's rough drive), and Send to <person>'s phone.
- Day: a day of the week ahead as its own timeline, what's due, its weather.
- Weather: the rest of today, hour by hour.
- Person: someone's whole day: their events, every routine with its steps, their chores and
  to-dos for today.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any

from themi import clock
from themi.core import keys
from themi.localtime import to_utc_iso
from themi_home.wall_view import (
    COOKING,
    Chip,
    TodayLine,
    WallEvent,
    WallItem,
    WallPerson,
    WallSection,
    WallView,
    _done_item,
    _for_both,
    _rank,
    current_routine,
    last_routine,
    lay_out_today,
    since,
    step_emoji,
)

if TYPE_CHECKING:
    from themi.accounts import Member
    from themi.core.calendar_view import Entry

DAYS_AHEAD = 13  # the Day view goes from today to two weeks out
NOTES_SHOWN = 280  # WL7: an event's notes, shortened for the Event view


def shorten(notes: str, most: int = NOTES_SHOWN) -> str:
    """An event's notes cut at a word, with an ellipsis when there was more."""
    if len(notes) <= most:
        return notes
    cut = notes[:most].rsplit(None, 1)[0] if " " in notes[:most] else notes[:most]
    return cut.rstrip(" ,.;:") + "\u2026"


@dataclass(frozen=True)
class EventView:
    whose: str  # "Erin's calendar", "the Madicen Family calendar"
    title: str
    when: str  # "Today, 6:30-8:30 pm", with an en dash
    status: str  # "Happening now · 48 minutes left", "Starts in 2 hours", "Finished"
    place: str
    video: bool
    leave_by: str  # "Leave around 6:05", or ""
    send_to: tuple[tuple[int, str], ...]  # who can have it on their phone
    ref: str
    sent: str = ""  # "Sent to Erin's phone."
    notes: str = ""  # WL7: the event's notes, shortened; "" for a Busy event
    tone: str = ""  # WL9a: its row's colour, for the card


@dataclass(frozen=True)
class Due:
    title: str
    whose: str


@dataclass(frozen=True)
class DayView:
    day: date
    heading: str  # "Tuesday, November 24"
    near: str  # "Tomorrow", "In 5 days"
    line: TodayLine
    due: tuple[Due, ...]
    weather: str  # "High 58°, low 47°", or ""
    icon: str  # a data URI, or ""
    before: str  # the day before, ISO, or "" at today
    after: str
    tone: str = ""  # WL9a: the family's colour, for the card


@dataclass(frozen=True)
class HourView:
    label: str  # "8 pm"
    temp: str
    chance: str  # "40%", or "" under 10%
    icon: str


@dataclass(frozen=True)
class WeatherView:
    heading: str
    high: str
    low: str
    alert: str
    hours: tuple[HourView, ...]


@dataclass(frozen=True)
class ScheduleRow:
    """WL9d: one of today's events on a person's page."""

    when: str  # "All day", "10-11 am", "6:30-8:30 pm", with an en dash
    title: str  # "Busy" when their calendar's details aren't shared
    past: bool = False
    now: bool = False


@dataclass(frozen=True)
class RoutinePart:
    """WL9d: a routine on a person's page: this part of the day's open, the rest folded."""

    id: int
    title: str  # "Morning routine"
    section: WallSection
    open: bool

    @property
    def left(self) -> int:
        return sum(1 for i in self.section.items if not i.done)

    @property
    def summary(self) -> str:
        """The folded line's words after the title: "4 steps, all done", "1 step"."""
        steps = len(self.section.items)
        said = f"{steps} step{'' if steps == 1 else 's'}"
        done = steps - self.left
        return (
            f"{said}, all done"
            if steps and not self.left
            else f"{said}, {done} done"
            if done
            else said
        )


@dataclass(frozen=True)
class PersonView:
    member_id: int
    name: str
    tone: str
    events: tuple[Chip, ...]  # with their times in the title
    sections: tuple[WallSection, ...]  # everything tappable on it (a tap finds its item here)
    # WL9d: the page
    day: str = ""  # "Wednesday, October 21"
    headline: str = ""  # "3 done tonight", or the part of the day
    listed: str = ""  # "4 chores and 3 to-dos on your list"
    schedule: tuple[ScheduleRow, ...] = ()
    breathe: str = ""  # "Nothing else this evening", when nothing else is on
    routines: tuple[RoutinePart, ...] = ()  # this part of the day's first
    chores: WallSection | None = None
    todos: WallSection | None = None
    opened: int = 0  # a folded routine unfolded


@dataclass(frozen=True)
class TogetherView:
    """WL9d: the Together page: the family's open things and what's done today."""

    day: str
    tone: str
    headline: str  # "This evening"
    line: str  # "4 open · 3 done"
    either: WallSection
    family: WallSection
    done: tuple[WallItem, ...]  # with who did it; a tap unticks
    people: tuple[WallPerson, ...] = ()  # for "Who did it?"


class WallViews:
    def __init__(self, view: WallView) -> None:
        self.view = view
        self.services = view.services

    # ----- Event ------------------------------------------------------------------------

    def event(self, day: date, member_id: int, calendar_id: str, event_id: str) -> EventView | None:
        found = next(
            (
                e
                for e in self.view.events(day)
                if e.member_id == member_id
                and e.calendar_id == calendar_id
                and e.event_id == event_id
            ),
            None,
        )
        if found is None:
            return None
        people = self.view.people()
        names = {m.id: m.name for m in people}
        family = found.row == "family"
        send_to = (
            tuple((m.id, m.name) for m in people)
            if family
            else ((member_id, names.get(member_id, "")),)
        )
        return EventView(
            whose="the family calendar" if family else f"{names.get(member_id, '')}'s calendar",
            title=found.title,
            when=_when(found, self.view.now()),
            status=_status(found, self.view.now()),
            place=found.place,
            video=found.video and found.title != "Busy",
            leave_by=self._leave_by(found, member_id),
            send_to=send_to,
            ref=found.ref,
            notes=shorten(found.notes),
            tone=found.tone,
        )

    def _leave_by(self, event: WallEvent, member_id: int) -> str:
        travel = self.services.maybe(keys.travel)
        if travel is None or not event.place or event.start <= self.view.now():
            return ""
        entry = self._entry(event)
        if entry is None:
            return ""
        minutes = travel.rough_drive(self.services.store.get_member(member_id), entry)
        if not minutes:
            return ""
        return f"Leave around {_clock(event.start - timedelta(minutes=minutes))}"

    def _entry(self, event: WallEvent) -> Entry | None:
        reader = self.services.maybe(keys.calendars)
        if reader is None:
            return None
        member = self.services.store.get_member(event.member_id)
        start = event.start.replace(hour=0, minute=0, second=0, microsecond=0)
        return next(
            (
                e
                for e in reader.entries(member, start, start + timedelta(days=1))
                if e.calendar_id == event.calendar_id and e.event_id == event.event_id
            ),
            None,
        )

    async def send_event(self, view: EventView, event_day: date, to: Member) -> str:
        """The event on their phone, through the outbox (WL5a's Send to my phone)."""
        from themi.channels.outbox import Priority

        lines = [f"From the wall: {view.title}", view.when]
        if view.place:
            lines.append(f"At {view.place}")
        if view.leave_by:
            lines.append(view.leave_by)
        outbox = self.services.outbox
        await outbox.send(to, "\n".join(lines), priority=Priority.REPLY, kind="wall")
        return f"Sent to {to.name}'s phone."

    # ----- Day --------------------------------------------------------------------------

    def day(self, day: date) -> DayView | None:
        now = self.view.now()
        today = now.date()
        if not (today <= day <= today + timedelta(days=DAYS_AHEAD)):
            return None
        rows = self.view.timeline_rows()
        live = day == today
        moment = now if live else datetime.combine(day, now.time().min, tzinfo=now.tzinfo)
        line = lay_out_today(moment, rows, self.view.events(day), [], live=live)
        weather, icon = self._day_weather(day)
        offset = (day - today).days
        return DayView(
            day=day,
            heading=f"{day:%A}, {day:%B} {day.day}",
            near="Today" if offset == 0 else "Tomorrow" if offset == 1 else f"In {offset} days",
            line=line,
            due=self._due(day),
            weather=weather,
            icon=icon,
            before=(day - timedelta(days=1)).isoformat() if day > today else "",
            after=(day + timedelta(days=1)).isoformat() if offset < DAYS_AHEAD else "",
            tone=self.view.together_tone(),
        )

    def _due(self, day: date) -> tuple[Due, ...]:
        names = {m.id: m.name for m in self.view.people()}
        tasks = self.view._open_tasks(self.view.people())
        due = sorted((t for t in tasks if t.due_on == day), key=lambda t: _rank(t, day))
        return tuple(
            Due(t.title, "Either of you" if _for_both(t) else names.get(t.assignee or 0, ""))
            for t in due
        )

    def _day_weather(self, day: date) -> tuple[str, str]:
        from themi.drawing.svg import icon
        from themi.standard.day_card import ICONS, degrees

        weather = self.services.maybe(keys.weather)
        forecast = weather.latest() if weather is not None else None
        found = forecast.day(day) if forecast is not None else None
        if weather is None or found is None:
            return "", ""
        units = weather.settings.units
        words = f"High {degrees(found.high, units)}, low {degrees(found.low, units)}"
        return words, icon(ICONS.get(found.code, "overcast")) if found.code else ""

    # ----- Weather ----------------------------------------------------------------------

    def weather(self) -> WeatherView | None:
        from themi.drawing.svg import icon
        from themi.standard.day_card import ICONS, degrees

        shown = self.view.weather()
        weather = self.services.maybe(keys.weather)
        forecast = weather.latest() if weather is not None else None
        if shown is None or weather is None or forecast is None:
            return None
        now = self.view.now()
        start = now.replace(minute=0, second=0, microsecond=0)
        units = weather.settings.units
        hours = tuple(
            HourView(
                _clock(at),
                degrees(h.temp, units),
                f"{h.chance}%" if h.chance >= 10 else "",
                icon(ICONS.get(h.code, "overcast")),
            )
            for h in forecast.hours
            if (at := h.at.astimezone(now.tzinfo)).date() == now.date() and at >= start
        )
        return WeatherView(
            heading=f"{now:%A}, {now:%B} {now.day}",
            high=shown.high,
            low=shown.low,
            alert=shown.alert,
            hours=hours,
        )

    # ----- Person -----------------------------------------------------------------------

    def person(self, member_id: int, opened: int = 0) -> PersonView | None:
        people = self.view.people()
        index = next((i for i, m in enumerate(people) if m.id == member_id), None)
        if index is None:
            return None
        member = people[index]
        now = self.view.now()
        today = now.date()
        mine = sorted(
            (e for e in self.view.events(today) if e.row == f"m{member.id}"),
            key=lambda e: (not e.all_day, e.start),
        )
        events = tuple(
            Chip(f"{_clock(e.start)} {e.title}" if not e.all_day else e.title, e.tone) for e in mine
        )
        schedule = tuple(_schedule_row(e, now) for e in mine)
        ahead = any(not e.all_day and e.end > now for e in mine)
        routines = self._routine_parts(member, opened)
        chores, todos = self._tasks(member, self.view.day_of(member))  # F59c: their day
        count = self.view._done_today(member)
        return PersonView(
            member_id=member.id,
            name=member.name,
            tone=self.view.tone_of(member),
            events=events,
            sections=(*(r.section for r in routines), chores, todos),
            day=f"{now:%A}, {now:%B} {now.day}",
            headline=f"{count} done {self.view._today_word()}" if count else self.view._part_word(),
            listed=_listed(
                sum(1 for i in chores.items if not i.done),
                sum(1 for i in todos.items if not i.done),
            ),
            schedule=schedule,
            breathe="" if ahead else f"Nothing else {self.view._part_word().lower()}",
            routines=routines,
            chores=chores,
            todos=todos,
            opened=opened,
        )

    def _routine_parts(self, member: Member, opened: int) -> tuple[RoutinePart, ...]:
        """Each routine for today: the one for this part of the day (or the last one, while
        a step is open: F55c) first and open, the rest folded unless `opened`."""
        routines = self.services.maybe(keys.routines)
        if routines is None:
            return ()
        day = routines.today(member)
        now = self.view.now()
        live = current_routine(routines, member, now)
        current = live or last_routine(routines, member, now)
        parts = [
            RoutinePart(
                routine.id,
                f"{routine.name} routine",
                section,
                open=routine.id == opened or (current is not None and routine.id == current.id),
            )
            for routine in routines.of(member)
            if (section := self._routine_section(routines, routine, day)).items
        ]
        if (
            live is None
            and current is not None
            and all(i.done for p in parts if p.id == current.id for i in p.section.items)
        ):
            # F55c: the last one (its window over) only stays first while a step is open
            parts = [replace(p, open=p.id == opened) if p.id == current.id else p for p in parts]
        first = [p for p in parts if current is not None and p.id == current.id and p.open]
        return (*first, *(p for p in parts if p not in first))

    def _routine_section(self, routines: Any, routine: Any, day: date) -> WallSection:
        return WallSection(
            routine.name,
            tuple(
                WallItem(
                    f"step-{item.id}-{day.isoformat()}",
                    item.title,
                    done=routines.ticked(item, day),
                    emoji=step_emoji(item.title),
                )
                for item in routines.today_items(routine, day)
            ),
            empty="Nothing set",
        )

    # ----- Together ---------------------------------------------------------------------

    def together(self, asking: str = "") -> TogetherView:
        view = self.view
        people = view.people()
        names = {m.id: m.name for m in people}
        now = view.now()
        today = view.household_day()  # F59c
        both = [t for t in view._open_tasks(people) if _for_both(t)]
        either = sorted(
            (t for t in both if t.repeats and t.due_on is not None and t.due_on <= today),
            key=lambda t: _rank(t, today),
        )
        family = sorted((t for t in both if not t.repeats), key=lambda t: _rank(t, today))
        done = tuple(
            _done_item(t, f"{names[by]} did it" if by in names else "", emoji=view.emoji_of(t))
            for t, by, _ in view._done_tasks(people, view.since(None))
            if _for_both(t)
        )

        def items(tasks: list[Any]) -> tuple[WallItem, ...]:
            return tuple(
                replace(i, asking=True) if i.key == asking else i
                for i in (view._task_item(t, today) for t in tasks)
            )

        open_count = len(either) + len(family)
        return TogetherView(
            day=f"{now:%A}, {now:%B} {now.day}",
            tone=view.together_tone(),
            headline=view._part_word(),
            line=f"{open_count} open · {len(done)} done",
            either=WallSection("Either of you", items(either), empty="Nothing due"),
            family=WallSection("Family to-do", items(family), empty="Nothing on the list"),
            done=done,
            people=tuple(WallPerson(m.id, m.name, view.tone_of(m)) for m in people),
        )

    def find_together(self, key: str) -> WallItem | None:
        view = self.together()
        return next(
            (i for i in (*view.either.items, *view.family.items, *view.done) if i.key == key), None
        )

    def _tasks(self, member: Member, today: date) -> tuple[WallSection, WallSection]:
        tasks = self.view._open_tasks([member])
        mine = [t for t in tasks if t.assignee == member.id and not _for_both(t)]
        chores = sorted(
            (
                t
                for t in mine
                if t.repeats
                and t.due_on is not None
                and t.due_on <= today
                and not self.view.held(t, member)  # F59c: as their chart shows
            ),
            key=lambda t: _rank(t, today),
        )
        todos = sorted(
            (t for t in mine if not t.repeats and (t.due_on is None or t.due_on <= today)),
            key=lambda t: _rank(t, today),
        )
        done = [
            t
            for t, _, _ in self.view._done_tasks([member], self.view.since(member))
            if t.assignee == member.id and not _for_both(t)
        ]
        shown = {t.id for t in chores} | {t.id for t in todos}
        finished = [t for t in done if t.id not in shown]
        return (
            WallSection(
                "Chores",
                tuple(self.view._task_item(t, today) for t in chores)
                + tuple(_done_item(t, emoji=self.view.emoji_of(t)) for t in finished if t.repeats),
                empty="Nothing due",
            ),
            WallSection(
                "To-do",
                tuple(self.view._task_item(t, today) for t in todos)
                + tuple(
                    _done_item(t, emoji=self.view.emoji_of(t)) for t in finished if not t.repeats
                ),
                empty="Nothing on the list",
            ),
        )

    def find(self, member_id: int, key: str) -> WallItem | None:
        """An item showing in someone's Person view, for a tap made there."""
        view = self.person(member_id)
        if view is None:
            return None
        return next((i for s in view.sections for i in s.items if i.key == key), None)


# ----- words -----------------------------------------------------------------------------


def _schedule_row(event: WallEvent, now: datetime) -> ScheduleRow:
    from themi.standard.day_card import span_words

    when = "All day" if event.all_day else span_words(event.start, event.end)
    live = not event.all_day and event.start <= now < event.end
    return ScheduleRow(when, event.title, past=event.end <= now, now=live)


def _listed(chores: int, todos: int) -> str:
    """ "4 chores and 3 to-dos on your list": never a score, just what's there."""
    parts = [
        f"{n} {word}{'' if n == 1 else 's'}"
        for n, word in ((chores, "chore"), (todos, "to-do"))
        if n
    ]
    return f"{' and '.join(parts)} on your list" if parts else "Nothing on your list"


def _clock(at: datetime) -> str:
    hour = at.hour % 12 or 12
    minutes = f":{at.minute:02d}" if at.minute else ""
    if at.hour == 12 and at.minute == 0:
        return "noon"
    return f"{hour}{minutes} {'am' if at.hour < 12 else 'pm'}"


def _when(event: WallEvent, now: datetime) -> str:
    from themi.standard.day_card import span_words

    offset = (event.start.date() - now.date()).days
    day = (
        "Today"
        if offset == 0
        else "Tomorrow"
        if offset == 1
        else f"{event.start:%A}, {event.start:%B} {event.start.day}"
    )
    return f"{day}, all day" if event.all_day else f"{day}, {span_words(event.start, event.end)}"


def _status(event: WallEvent, now: datetime) -> str:
    if event.end <= now:
        return "Finished"
    if event.all_day:
        return ""
    if event.start <= now:
        return f"Happening now · {_span(event.end - now)} left"
    if event.start.date() != now.date():
        return ""
    return f"Starts in {_span(event.start - now)}"


def _span(gap: timedelta) -> str:
    minutes = max(1, round(gap.total_seconds() / 60))
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''}"
    hours, rest = divmod(minutes, 60)
    whole = f"{hours} hour{'s' if hours != 1 else ''}"
    return whole if rest < 10 else f"{whole} {rest} minutes"


# ----- WL5b: List, Dish and Note --------------------------------------------------------

LATELY = timedelta(days=7)


@dataclass(frozen=True)
class ListRow:
    id: int
    title: str
    sub: str = ""
    open: bool = False  # its menu is showing


@dataclass(frozen=True)
class ListView:
    which: str  # "todo/3", "todo/family", "groceries"
    title: str  # "Erin's to-do list"
    tone: str
    rows: tuple[ListRow, ...]
    lately: tuple[str, ...] = ()  # ticked off in the last week
    give_to: tuple[tuple[int, str], ...] = ()  # the others it can go to
    family: bool = False  # "Make it a family to-do" is offered
    groceries: bool = False
    said: str = ""  # what the last change did
    shared_with: tuple[str, ...] = ()  # WL9a: the household, for the Groceries foot
    named: bool = False  # F59e: a household list ("list/<id>"): tick, untick, add
    ticked: tuple[ListRow, ...] = ()  # F59e: its items ticked off in the last week


@dataclass(frozen=True)
class DishView:
    item_id: int
    name: str
    ingredients: tuple[str, ...]  # shopping items, from the recipe; () without one
    recipe: bool
    people: tuple[tuple[int, str], ...]
    said: str = ""
    tone: str = ""  # WL9a: the household's colour, for the card


@dataclass(frozen=True)
class NoteView:
    text: str
    why: str
    key: str
    chore: bool  # They're in / Later tonight / In the morning; else just Got it
    both: bool  # "Who brought them in?" with Both of us
    people: tuple[tuple[int, str], ...]
    asking: bool = False
    said: str = ""


def list_view(views: WallViews, which: str, opened: int = 0, said: str = "") -> ListView | None:
    view = views.view
    people = view.people()
    today = view.now().date()
    if which == "groceries":
        groceries = views.services.maybe(keys.groceries)
        if groceries is None:
            return None
        rows = tuple(
            ListRow(g.id, g.name[:1].upper() + g.name[1:], open=g.id == opened)
            for g in groceries.needed()
        )
        return ListView(
            which,
            "Groceries",
            view.together_tone(),
            rows,
            groceries=True,
            said=said,
            shared_with=tuple(m.name for m in people),
        )
    if which.startswith("list/"):
        return _named_list(views, which, said)
    whose = which.removeprefix("todo/")
    tasks = view._open_tasks(people)
    if whose == "family":
        mine = [t for t in tasks if _for_both(t) and not t.repeats]
        owner, title, tone = None, "Family to-do", view.together_tone()
    elif whose.isdigit() and (index := _index(people, int(whose))) is not None:
        owner = people[index]
        mine = [t for t in tasks if t.assignee == owner.id and not _for_both(t) and not t.repeats]
        title, tone = f"{owner.name}'s to-do list", view.tone_of(owner)
    else:
        return None
    today = view.day_of(owner) if owner is not None else view.household_day()  # F59c
    rows = tuple(
        ListRow(
            t.id, t.title, since(t.due_on, today) or _due_words(t.due_on, today), t.id == opened
        )
        for t in sorted(mine, key=lambda t: _rank(t, today))
    )
    lately = _lately(views, people, owner)
    others = tuple((m.id, m.name) for m in people if owner is None or m.id != owner.id)
    return ListView(which, title, tone, rows, lately, others, family=owner is not None, said=said)


def _named_list(views: WallViews, which: str, said: str) -> ListView | None:
    """F59e (idea #254): a household list from the wall's bottom strip, all of it: tap to
    tick off, the last week's ticks to put back, and an add box. Not a personal list, nor
    one with a purpose of its own (Things to Buy)."""
    lists = views.services.maybe(keys.lists)
    people = views.view.people()
    list_id = which.removeprefix("list/")
    if lists is None or not people or not list_id.isdigit():
        return None
    nl = lists.get(int(list_id), people[0])
    if nl is None or nl.personal or nl.purpose is not None:
        return None
    since = to_utc_iso(clock.now() - LATELY)
    rows = views.services.store.db.query(
        "SELECT id, name FROM list_items WHERE list_id = ? AND done = 1 AND done_at >= ? "
        "ORDER BY done_at DESC",
        (nl.id, since),
    )
    return ListView(
        which,
        nl.name,
        views.view.together_tone(),
        tuple(ListRow(i.id, i.name) for i in nl.open_items),
        said=said,
        named=True,
        ticked=tuple(ListRow(int(r["id"]), str(r["name"])) for r in rows),
    )


def _index(people: list[Member], member_id: int) -> int | None:
    return next((i for i, m in enumerate(people) if m.id == member_id), None)


def _due_words(due: date | None, today: date) -> str:
    if due is None:
        return ""
    if due == today:
        return "today"
    if due == today + timedelta(days=1):
        return "tomorrow"
    return f"{due:%a %b} {due.day}"


def _lately(views: WallViews, people: list[Member], owner: Member | None) -> tuple[str, ...]:
    board = views.services.maybe(keys.taskboard)
    if board is None:
        return ()
    now = views.view.now()
    seen: dict[int, str] = {}
    for member in [owner] if owner is not None else people:
        for done in board.done_between(member, now - LATELY, now + timedelta(seconds=1)):
            task = done.task
            if task.repeats or task.off_displays:
                continue
            if (owner is None) == _for_both(task) and (owner is None or task.assignee == owner.id):
                seen.setdefault(task.id, task.title)
    return tuple(seen.values())


@dataclass(frozen=True)
class DishesView:
    """WL9b: the household's Things to cook, numbered; one dish unfolded at most."""

    title: str  # the list's own name
    tone: str
    dishes: tuple[tuple[int, str], ...]
    open: DishView | None = None


def dishes_view(views: WallViews, opened: int = 0, said: str = "") -> DishesView | None:
    lists = views.services.maybe(keys.lists)
    people = views.view.people()
    if lists is None or not people:
        return None
    found = next(
        (
            nl
            for nl in lists.visible(people[0])
            if not nl.personal and nl.purpose is None and COOKING.search(nl.name)
        ),
        None,
    )
    if found is None:
        return None
    dishes = tuple((i.id, i.name) for i in found.open_items)
    dish = dish_view(views, opened, said) if opened in {i for i, _ in dishes} else None
    return DishesView(found.name, views.view.together_tone(), dishes, dish)


def dish_view(views: WallViews, item_id: int, said: str = "") -> DishView | None:
    """A Things to cook item: its recipe's ingredients as shopping items (as already read,
    or by rule: never a model call on the wall), or the item alone without a recipe."""
    lists = views.services.maybe(keys.lists)
    people = views.view.people()
    if lists is None or not people:
        return None
    item = next(
        (
            i
            for nl in lists.visible(people[0])
            if not nl.personal
            for i in nl.open_items
            if i.id == item_id
        ),
        None,
    )
    if item is None:
        return None
    recipe = _recipe(views, item.name)
    shopping = views.services.maybe(keys.recipe_groceries)
    names: tuple[str, ...] = ()
    if recipe is not None and shopping is not None:
        names = tuple(dict.fromkeys(i.item for i in shopping.known(recipe) if i.item))
    return DishView(
        item_id,
        item.name,
        names,
        recipe is not None,
        tuple((m.id, m.name) for m in people),
        said,
        views.view.together_tone(),
    )


def _recipe(views: WallViews, name: str) -> Any:
    recipes = views.services.maybe(keys.recipes)
    if recipes is None:
        return None
    matches = recipes.find(name, charts=False)
    best = matches[0] if matches else None
    if best is None or not (best.exact or best.name_hits == best.wanted):
        return None
    return best.recipe


def note_view(views: WallViews, asking: bool = False, said: str = "") -> NoteView | None:
    note = views.view.note()
    if note is None:
        return None
    return NoteView(
        note.text,
        note.why,
        note.key,
        chore=note.task_id is not None,
        both=note.both,
        people=tuple((m.id, m.name) for m in views.view.people()),
        asking=asking,
        said=said,
    )
