"""The week ahead (DC6; the Day Card Plan's "Other uses").

Seven columns, today first: each day's events as blocks at their times on one shared hour
axis, with the day's weather icon, high and low on top. On request only ("show my week",
`/week`); it's never pushed.

Events are the day card's (their own, their partner's shared ones, task blocks quieter); a
week has no travel lead-ins and no "what's waiting".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any

from themi.accounts import Member
from themi.core import keys
from themi.drawing.layout import Span, Timeline, hour_label, place
from themi.drawing.svg import write_svg
from themi.drawing.text import fit
from themi.standard.day_card import ICONS, THEMES, CardEvent, DayCard, degrees, span_words
from themi.standard.drawings import DrawingsPreferences

if TYPE_CHECKING:
    from themi.core.services import Services

WIDTH, HEIGHT = 840, 560  # landscape; drawn at twice that
PNG_WIDTH = 1680
PAD = 24
DAYS = 7
CAPTION = "Your week ahead."
NOTHING_TEXT = "Nothing on the calendar this week."


@dataclass(frozen=True)
class WeekDay:
    day: date
    events: tuple[CardEvent, ...] = ()
    high: float | None = None  # °F
    low: float | None = None
    icon: str | None = None


@dataclass(frozen=True)
class WeekCardData:
    name: str
    today: date
    days: tuple[WeekDay, ...]
    units: str = "F"


class WeekCard:
    def __init__(self, services: Services, day_card: DayCard) -> None:
        self.services = services
        self.day_card = day_card

    def data(self, member: Member, first: date | None = None) -> WeekCardData:
        today = self.day_card.today(member)
        first = first or today
        weather = self.services.maybe(keys.weather)
        forecast = weather.latest() if weather is not None else None
        days = []
        for i in range(DAYS):
            day = first + timedelta(days=i)
            start = self.day_card.start(member, day)
            events = tuple(e for e in self.day_card.events(member, day, start, travel=False))
            found = forecast.day(day) if forecast is not None else None
            days.append(
                WeekDay(
                    day=day,
                    events=events,
                    high=found.high if found else None,
                    low=found.low if found else None,
                    icon=ICONS.get(found.code, "overcast") if found and found.code else None,
                )
            )
        units = weather.settings.units if weather is not None else "F"
        return WeekCardData(member.name, today, tuple(days), units)

    def svg(self, member: Member) -> str:
        prefs = self.services.store.preferences(member.id, DrawingsPreferences)
        return week_svg(self.data(member), prefs.picture_theme)

    async def png(self, member: Member) -> bytes | None:
        drawings = self.services.maybe(keys.drawings)
        if drawings is None:
            return None
        return await drawings.png(self.svg(member), PNG_WIDTH)

    async def send(self, member: Member) -> bool:
        """The week as a picture, as a reply; the words when it can't be drawn or the
        channel shows no pictures. True when a picture went."""
        from themi.channels.outbox import Priority

        data = self.data(member)
        png = await self.png(member)
        if png is not None:
            sent = await self.services.outbox.send_photo(member, png, CAPTION, kind="week")
            if sent is not None:
                return True
        await self.services.outbox.send(
            member, week_text(data), priority=Priority.REPLY, kind="week"
        )
        return False


# ----- in words ---------------------------------------------------------------------------


def week_text(data: WeekCardData) -> str:
    """The week in words, for a channel without pictures."""
    lines = []
    for day in data.days:
        timed = sorted((e for e in day.events if not e.all_day), key=lambda e: e.start)
        all_day = [e.title for e in day.events if e.all_day]
        parts = all_day + [f"{_short(e.start)} {e.title}" for e in timed]
        if parts:
            lines.append(f"- {day.day:%a %d}: {'; '.join(parts)}")
    if not lines:
        return NOTHING_TEXT
    return "The week ahead:\n" + "\n".join(lines)


def _short(at: datetime) -> str:
    hour = at.hour % 12 or 12
    clock = f"{hour}" if at.minute == 0 else f"{hour}:{at.minute:02d}"
    return f"{clock} {'am' if at.hour < 12 else 'pm'}"


# ----- drawing it -------------------------------------------------------------------------


def _hours(data: WeekCardData) -> tuple[float, float]:
    """The hours the axis runs: 8 am to 9 pm, wider for an earlier or later event."""
    lo, hi = 8.0, 21.0
    for day in data.days:
        for e in day.events:
            if e.all_day:
                continue
            midnight = datetime(day.day.year, day.day.month, day.day.day, tzinfo=e.start.tzinfo)
            start = max((e.start - midnight).total_seconds() / 3600, 0.0)
            end = min((e.end - midnight).total_seconds() / 3600, 24.0)
            lo, hi = min(lo, float(int(start))), max(hi, float(-int(-end)))
    return lo, hi


def view(data: WeekCardData, theme: str = "light") -> dict[str, Any]:
    colors = THEMES[theme]
    x0, x1 = PAD + 44.0, WIDTH - PAD
    col_w = (x1 - x0) / DAYS
    lo, hi = _hours(data)
    ref = datetime(2000, 1, 3, tzinfo=UTC)  # a reference day: every column shares one hour axis
    top, bottom = 176.0, HEIGHT - PAD
    line = Timeline(ref + timedelta(hours=lo), ref + timedelta(hours=hi), top, bottom - top)
    step = 2 if hi - lo <= 14 else 3
    ticks = [
        {"y": line.y(ref + timedelta(hours=h)), "label": hour_label(ref + timedelta(hours=h))}
        for h in range(int(lo), int(hi) + 1, step)
    ]
    columns = []
    for i, day in enumerate(data.days):
        cx = x0 + i * col_w
        midnight = None
        timed = [e for e in day.events if not e.all_day]
        spans = []
        for e in timed:
            midnight = datetime(day.day.year, day.day.month, day.day.day, tzinfo=e.start.tzinfo)
            spans.append(Span(e.key, ref + (e.start - midnight), ref + (e.end - midnight)))
        by_key = {e.key: e for e in timed}
        blocks = []
        for p in place(spans, line, cx + 3, col_w - 6):
            e = by_key[p.key]
            kind = e.kind
            lines = []
            if p.height >= 11:
                size = 10.5 if p.height >= 15 else 9
                lines.append(
                    {"y": p.y + min(p.height / 2, 9) + size / 3 + (1 if p.height >= 15 else 0),
                     "size": size, "bold": kind not in ("held", "travel"),
                     "text": fit(e.title, size, p.width - 8, bold=kind not in ("held",))}
                )  # fmt: skip
            if p.height >= 34:
                lines.append(
                    {"y": p.y + 26, "size": 9, "bold": False,
                     "text": fit(span_words(e.start, e.end), 9, p.width - 8)}
                )  # fmt: skip
            blocks.append(
                {
                    "x": p.x,
                    "y": p.y,
                    "width": p.width,
                    "height": p.height,
                    "fill": "none" if kind == "held" else colors[
                        "partner" if kind == "partner" else "event"
                    ],
                    "edge": colors[
                        "held_edge" if kind == "held" else
                        "partner_edge" if kind == "partner" else "event_edge"
                    ],
                    "dashed": kind == "held",
                    "muted": kind == "held",
                    "lines": lines,
                }
            )  # fmt: skip
        all_day = [e for e in day.events if e.all_day]
        strip = None
        if all_day:
            more = f" +{len(all_day) - 1}" if len(all_day) > 1 else ""
            strip = fit(all_day[0].title, 10, col_w - 14 - len(more) * 6, bold=True) + more
        weather = None
        if day.high is not None and day.low is not None:
            weather = {
                "icon": day.icon,
                "text": f"{degrees(day.high, data.units)} / {degrees(day.low, data.units)}",
            }
        columns.append(
            {
                "x": cx,
                "mid": cx + col_w / 2,
                "width": col_w,
                "name": f"{day.day:%a}",
                "date": f"{day.day.day}",
                "today": day.day == data.today,
                "weather": weather,
                "strip": strip,
                "blocks": blocks,
            }
        )
    first, last = data.days[0].day, data.days[-1].day
    return {
        "width": WIDTH,
        "height": HEIGHT,
        "pad": PAD,
        "c": colors,
        "title": "The week ahead",
        "subtitle": f"{data.name} · {first:%a} {first.day} {first:%b} to "
        f"{last:%a} {last.day} {last:%b}",
        "x0": x0,
        "x1": x1,
        "top": top,
        "bottom": bottom,
        "ticks": ticks,
        "columns": columns,
        "empty": not any(d.events for d in data.days),
    }


def week_svg(data: WeekCardData, theme: str = "light") -> str:
    return write_svg("week_card.svg", **view(data, theme))
