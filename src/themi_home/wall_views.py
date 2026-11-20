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

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

from themi.core import keys
from themi_home.wall_view import (
    Chip,
    TodayLine,
    WallEvent,
    WallItem,
    WallSection,
    WallView,
    _done_item,
    _for_both,
    _rank,
    lay_out_today,
    since,
)

if TYPE_CHECKING:
    from themi.accounts import Member
    from themi.core.calendar_view import Entry

DAYS_AHEAD = 13  # the Day view goes from today to two weeks out


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
class PersonView:
    member_id: int
    name: str
    tone: str
    events: tuple[Chip, ...]  # with their times in the title
    sections: tuple[WallSection, ...]


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
        rows = [(f"m{m.id}", m.name, f"p{i % 4}") for i, m in enumerate(self.view.people())]
        rows.append(("family", "Family", "family"))
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

    def person(self, member_id: int) -> PersonView | None:
        people = self.view.people()
        index = next((i for i, m in enumerate(people) if m.id == member_id), None)
        if index is None:
            return None
        member = people[index]
        now = self.view.now()
        today = now.date()
        events = tuple(
            Chip(f"{_clock(e.start)} {e.title}" if not e.all_day else e.title, e.tone)
            for e in sorted(self.view.events(today), key=lambda e: (not e.all_day, e.start))
            if e.row == f"m{member.id}"
        )
        return PersonView(
            member_id=member.id,
            name=member.name,
            tone=f"p{index % 4}",
            events=events,
            sections=(*self._routines(member), *self._tasks(member, today)),
        )

    def _routines(self, member: Member) -> list[WallSection]:
        routines = self.services.maybe(keys.routines)
        if routines is None:
            return []
        day = routines.today(member)
        return [
            WallSection(
                routine.name,
                tuple(
                    WallItem(
                        f"step-{item.id}-{day.isoformat()}",
                        item.title,
                        done=routines.ticked(item, day),
                    )
                    for item in routines.today_items(routine, day)
                ),
                empty="Nothing set",
            )
            for routine in routines.of(member)
        ]

    def _tasks(self, member: Member, today: date) -> list[WallSection]:
        tasks = self.view._open_tasks([member])
        mine = [t for t in tasks if t.assignee == member.id and not _for_both(t)]
        chores = sorted(
            (t for t in mine if t.repeats and t.due_on is not None and t.due_on <= today),
            key=lambda t: _rank(t, today),
        )
        todos = sorted(
            (t for t in mine if not t.repeats and (t.due_on is None or t.due_on <= today)),
            key=lambda t: _rank(t, today),
        )
        done = [
            t
            for t, _ in self.view._done_tasks([member])
            if t.assignee == member.id and not _for_both(t)
        ]
        shown = {t.id for t in chores} | {t.id for t in todos}
        finished = [t for t in done if t.id not in shown]
        return [
            WallSection(
                "Chores",
                tuple(WallItem(f"task-{t.id}", t.title, since(t.due_on, today)) for t in chores)
                + tuple(_done_item(t) for t in finished if t.repeats),
                empty="Nothing due",
            ),
            WallSection(
                "To-do",
                tuple(WallItem(f"task-{t.id}", t.title, since(t.due_on, today)) for t in todos)
                + tuple(_done_item(t) for t in finished if not t.repeats),
                empty="Nothing on the list",
            ),
        ]

    def find(self, member_id: int, key: str) -> WallItem | None:
        """An item showing in someone's Person view, for a tap made there."""
        view = self.person(member_id)
        if view is None:
            return None
        return next((i for s in view.sections for i in s.items if i.key == key), None)


# ----- words -----------------------------------------------------------------------------


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
