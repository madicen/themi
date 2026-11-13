"""The day card: a picture of someone's day (DC3; the plan's "What the family sees").

Today's events as blocks at their times, the weather down the same hours, and a quiet
sign of what's waiting behind the morning message's buttons. Drawn from Themi's own data
by `themi.drawing`; sent with the morning message (DC5) and shown on the website (DC7).

- Events are the morning message's (their own and their partner's shared ones), plus the
  blocks Themi holds for tasks ("task-block:"), drawn quieter. A task's own copy
  ("task:") isn't drawn: it's a task, not a plan for the day.
- An event with a place gets a thin lead-in before it, "Leave around 1:20", from the rough
  drive time (places already found, no lookup, no traffic: a picture never waits on the
  network).
- The weather column is the hourly forecast: temperature as a line, the chance of rain or
  snow as bars. A noteworthy line (WX2) goes in a band at the top; an NWS alert (WX3) as a
  warning. Never advice, never energy.
- What's waiting is dots by default (`picture_counts`), never red, never "overdue".
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING, Any, Literal
from zoneinfo import ZoneInfo

from themi import clock
from themi.accounts import Member
from themi.core import keys
from themi.drawing.layout import Span, Timeline, all_day_rows, place, window
from themi.drawing.svg import write_svg
from themi.drawing.text import fit, text_width
from themi.standard.day_summary import DaySummaryPreferences
from themi.standard.drawings import DrawingsPreferences

if TYPE_CHECKING:
    from themi.core.calendar_view import Entry
    from themi.core.services import Services

WIDTH, HEIGHT = 540, 675  # the card's own units; drawn at twice that (1080 x 1350)
PNG_WIDTH = 1080
PAD = 28
DEFAULT_START = time(7)  # no morning time set: the day from 7 am
TRAVEL_TITLE = "Leave around {at}"

Kind = Literal["event", "partner", "held", "travel"]

# Open-Meteo's WMO weather codes to the bundled Meteocons (day versions; `_icon` swaps in
# the night ones for an hour after dark).
ICONS: dict[int, str] = {
    0: "clear-day",
    1: "partly-cloudy-day",
    2: "partly-cloudy-day",
    3: "overcast",
    45: "fog",
    48: "fog",
    51: "drizzle",
    53: "drizzle",
    55: "drizzle",
    56: "sleet",
    57: "sleet",
    61: "rain",
    63: "rain",
    65: "rain",
    66: "sleet",
    67: "sleet",
    71: "snow",
    73: "snow",
    75: "snow",
    77: "snow",
    80: "partly-cloudy-day-rain",
    81: "partly-cloudy-day-rain",
    82: "partly-cloudy-day-rain",
    85: "partly-cloudy-day-snow",
    86: "partly-cloudy-day-snow",
    95: "thunderstorms-rain",
    96: "thunderstorms-hail",
    99: "thunderstorms-hail",
}
# For the day's icon: the gravest weather that lasts (thunder, ice, snow, rain, ...).
GRAVITY = [95, 96, 99, 56, 57, 66, 67, 71, 73, 75, 77, 85, 86, 61, 63, 65, 80, 81, 82]
GRAVITY += [51, 53, 55, 45, 48, 3, 2, 1, 0]

THEMES: dict[str, dict[str, str]] = {
    "light": {
        "bg": "#FBFAF7",
        "ink": "#1F2328",
        "muted": "#6B6F76",
        "grid": "#E6E3DC",
        "event": "#DCEBFA",
        "event_edge": "#4A88C7",
        "partner": "#E8E1F6",
        "partner_edge": "#8569BF",
        "held_edge": "#9AA0A6",
        "travel": "#EEF4FB",
        "note": "#EEF0F3",
        "note_edge": "#C9CDD3",
        "alert": "#FFF1D6",
        "alert_edge": "#D99A2B",
        "temp": "#D9653B",
        "rain": "#3FA796",
        "chip_edge": "#C9CDD3",
    },
    "dark": {
        "bg": "#16181C",
        "ink": "#ECEDEE",
        "muted": "#9BA1A6",
        "grid": "#2A2E35",
        "event": "#1D3550",
        "event_edge": "#5AA0E6",
        "partner": "#2F2645",
        "partner_edge": "#A68BE0",
        "held_edge": "#6F767E",
        "travel": "#1A2633",
        "note": "#23272E",
        "note_edge": "#3A4049",
        "alert": "#3A2E14",
        "alert_edge": "#E0A73F",
        "temp": "#F08A5D",
        "rain": "#4FC1AE",
        "chip_edge": "#3A4049",
    },
}


# ----- the data ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CardEvent:
    key: str
    title: str
    start: datetime
    end: datetime
    kind: Kind = "event"
    place: str = ""
    all_day: bool = False


@dataclass(frozen=True)
class CardHour:
    at: datetime
    temp: float  # °F
    chance: int  # %
    code: int  # WMO


@dataclass(frozen=True)
class CardWeather:
    hours: tuple[CardHour, ...]
    high: float | None  # °F
    low: float | None
    units: str = "F"
    line: str | None = None
    alert: bool = False


@dataclass(frozen=True)
class Waiting:
    tasks: int = 0
    email: int = 0
    other: int = 0


@dataclass(frozen=True)
class DayCardData:
    name: str
    day: date
    start: datetime  # the morning message's time that day
    events: tuple[CardEvent, ...] = ()
    weather: CardWeather | None = None
    waiting: Waiting = field(default_factory=Waiting)


# ----- gathering it -----------------------------------------------------------------------


class DayCard:
    def __init__(self, services: Services) -> None:
        self.services = services

    def _tz(self) -> ZoneInfo:
        family = self.services.store.get_family()
        return ZoneInfo(family.timezone if family else "UTC")

    def today(self, member: Member) -> date:
        """Their day now (F34j: their own rollover), as the morning message has it."""
        summary = self.services.maybe(keys.day_summary)
        if summary is not None:
            return summary.today(member)
        return clock.now().astimezone(self._tz()).date()

    def start(self, member: Member, day: date) -> datetime:
        at = self.services.store.preferences(member.id, DaySummaryPreferences).morning_summary
        at = at or DEFAULT_START
        return datetime(day.year, day.month, day.day, at.hour, at.minute, tzinfo=self._tz())

    def data(self, member: Member, day: date) -> DayCardData:
        start = self.start(member, day)
        return DayCardData(
            name=member.name,
            day=day,
            start=start,
            events=tuple(self.events(member, day, start, scope="mine")),  # F42d
            weather=self._weather(start),
            waiting=self._waiting(member, day),
        )

    def events(
        self,
        member: Member,
        day: date,
        start: datetime,
        *,
        travel: bool = True,
        scope: str = "all",
    ) -> list[CardEvent]:
        """The day's events as the card draws them; `travel=False` without lead-ins (the
        week ahead, DC6). The day card itself is `scope="mine"` (F42d, idea #200): their own
        and the family calendar's, as the morning message's words are."""
        summary = self.services.maybe(keys.day_summary)
        if summary is None:
            return []
        travel_times = self.services.maybe(keys.travel) if travel else None
        tz = self._tz()
        out: list[CardEvent] = []
        for i, (entry, whose) in enumerate(summary.events(member, day, partner=True, scope=scope)):
            source = str(entry.source or "")
            if source.startswith("task:"):
                continue  # a task's own copy: a task, not a plan
            held = source.startswith("task-block:")
            kind: Kind = "held" if held else "partner" if whose else "event"
            out.append(
                CardEvent(
                    key=f"e{i}",
                    title=entry.title + whose,
                    start=entry.starts_at.astimezone(tz),
                    end=entry.ends_at.astimezone(tz),
                    kind=kind,
                    place="" if entry.video else entry.location,
                    all_day=entry.all_day,
                )
            )
            lead = self._lead_in(travel_times, member, entry, kind, start)
            if lead is not None:
                leave = entry.starts_at.astimezone(tz) - timedelta(minutes=lead)
                out.append(
                    CardEvent(
                        key=f"t{i}",
                        title=TRAVEL_TITLE.format(at=clock_words(leave)),
                        start=leave,
                        end=entry.starts_at.astimezone(tz),
                        kind="travel",
                    )
                )
        return out

    @staticmethod
    def _lead_in(
        travel: Any, member: Member, entry: Entry, kind: Kind, start: datetime
    ) -> int | None:
        if travel is None or kind != "event" or entry.all_day or entry.starts_at <= start:
            return None
        return travel.rough_drive(member, entry)

    def _weather(self, start: datetime) -> CardWeather | None:
        weather = self.services.maybe(keys.weather)
        forecast = weather.latest() if weather is not None else None
        if weather is None or forecast is None:
            return None
        today = forecast.day(start.date())
        hours = tuple(
            CardHour(h.at, h.temp, h.chance, h.code)
            for h in forecast.hours
            if h.at.astimezone(start.tzinfo).date() == start.date()
        )
        return CardWeather(
            hours=hours,
            high=today.high if today else None,
            low=today.low if today else None,
            units=weather.settings.units,
            line=weather.line(start),
            alert=weather.alert_in_force(start),
        )

    def _waiting(self, member: Member, day: date) -> Waiting:
        summary = self.services.maybe(keys.day_summary)
        trays = [r["tray"] for r in self.services.outbox.trayed(member.id)]
        due = len(summary.due(member, day)) if summary is not None else 0
        return Waiting(
            tasks=max(due, trays.count("tasks")),
            email=trays.count("email"),
            other=trays.count("other"),
        )

    def svg(self, member: Member, day: date) -> str:
        prefs = self.services.store.preferences(member.id, DrawingsPreferences)
        return card_svg(self.data(member, day), prefs.picture_counts, prefs.picture_theme)

    async def png(self, member: Member, day: date) -> bytes | None:
        drawings = self.services.maybe(keys.drawings)
        if drawings is None:
            return None
        return await drawings.png(self.svg(member, day), PNG_WIDTH)


# ----- drawing it -------------------------------------------------------------------------


def clock_words(at: datetime) -> str:
    """ "1:20", "2", for a time in a sentence where am or pm is plain."""
    hour = at.hour % 12 or 12
    return f"{hour}" if at.minute == 0 else f"{hour}:{at.minute:02d}"


def _hm(at: datetime) -> str:
    if at.hour == 12 and at.minute == 0:
        return "noon"
    return f"{clock_words(at)} {'am' if at.hour < 12 else 'pm'}"


def span_words(start: datetime, end: datetime) -> str:
    """ "2-3 pm", "10:30 am-12:15 pm", "noon-1 pm" (with en dashes)."""
    first, last = _hm(start), _hm(end)
    if first[-2:] == last[-2:] and first != "noon" and last != "noon":
        first = first[:-3]
    return f"{first}\u2013{last}"


def degrees(f: float, units: str) -> str:
    return f"{round((f - 32) * 5 / 9) if units == 'C' else round(f)}°"


def day_icon(hours: Sequence[CardHour], start: datetime, end: datetime) -> str:
    """The day's icon: the gravest weather that lasts two hours or more in the waking day
    (one hour, when nothing lasts), as a Meteocons name."""
    waking = [h.code for h in hours if start - timedelta(hours=1) < h.at < end]
    if not waking:
        return "overcast"
    lasting = [c for c in set(waking) if waking.count(c) >= 2] or waking
    known = [c for c in lasting if c in GRAVITY]
    code = min(known, key=GRAVITY.index) if known else max(lasting)
    return ICONS.get(code, "overcast")


def chip_words(label: str, count: int, counts: str, one: str, many: str) -> str:
    if counts == "numbers":
        return f"{count} {one if count == 1 else many}"
    dots = 1 if count <= 1 else 2 if count <= 3 else 3
    return f"{label} {'•' * dots}"


def view(data: DayCardData, counts: str = "dots", theme: str = "light") -> dict[str, Any]:
    """Every position and word on the card, for the template."""
    colors = THEMES[theme]
    tz = data.start.tzinfo
    timed = [e for e in data.events if not e.all_day]
    all_day = [e for e in data.events if e.all_day]
    spans = [Span(e.key, e.start, e.end) for e in timed]
    w_start, w_end = window(data.start, spans)

    y = 52.0
    header = {
        "date": f"{data.day:%A} {data.day.day} {data.day:%B}",
        "date_y": y,
        "name": f"{data.name}\u2019s day",
        "name_y": y + 24,
    }
    weather = data.weather
    top_right: dict[str, Any] | None = None
    if weather is not None and weather.high is not None and weather.low is not None:
        top_right = {
            "icon": day_icon(weather.hours, w_start, w_end),
            "high": degrees(weather.high, weather.units),
            "low": degrees(weather.low, weather.units),
        }
    y += 46
    band = None
    if weather is not None and weather.line:
        band = {
            "y": y,
            "text": fit(weather.line, 14, WIDTH - 2 * PAD - 28),
            "fill": colors["alert"] if weather.alert else colors["note"],
            "edge": colors["alert_edge"] if weather.alert else colors["note_edge"],
        }
        y += 34 + 10

    strip = []
    shown, more = all_day_rows([e.key for e in all_day])
    for key in shown:
        e = next(a for a in all_day if a.key == key)
        last = key == shown[-1] and more
        suffix = f"  +{more} more" if last else ""
        width = WIDTH - 2 * PAD - 56 - 16 - text_width(suffix, 12)
        strip.append(
            {
                "y": y,
                "title": fit(e.title, 13, width, bold=True),
                "more": suffix.strip(),
                "fill": colors["partner" if e.kind == "partner" else "event"],
                "edge": colors["partner_edge" if e.kind == "partner" else "event_edge"],
            }
        )
        y += 26
    if strip:
        y += 6

    footer_h = 0 if counts == "hide" or not _any_waiting(data.waiting) else 44
    top = y + 22
    bottom = HEIGHT - PAD - footer_h
    line = Timeline(w_start, w_end, top=top, height=bottom - top)
    events_x, weather_x = PAD + 52, WIDTH - PAD - 58
    events_w = (weather_x - 10 if weather else WIDTH - PAD) - events_x

    ticks = [{"y": t.y, "label": t.label} for t in line.ticks()]
    by_key = {e.key: e for e in timed}
    blocks = [_block(p, by_key[p.key], colors) for p in place(spans, line, events_x, events_w)]

    column = None
    if weather is not None and weather.hours:
        column = _weather_column(weather, line, weather_x, WIDTH - PAD, colors)

    chips = []
    if footer_h:
        x = PAD
        for label, count, one, many in (
            ("Tasks", data.waiting.tasks, "task", "tasks"),
            ("Email", data.waiting.email, "email", "emails"),
            ("Everything else", data.waiting.other, "other thing", "other things"),
        ):
            if count <= 0:
                continue
            words = chip_words(label, count, counts, one, many)
            width = text_width(words, 13) + 28
            chips.append({"x": x, "width": width, "text": words})
            x += width + 10
    return {
        "width": WIDTH,
        "height": HEIGHT,
        "pad": PAD,
        "c": colors,
        "header": header,
        "top_right": top_right,
        "band": band,
        "strip": strip,
        "strip_x": PAD + 52,
        "strip_w": WIDTH - 2 * PAD - 52,
        "timeline": {"top": top, "bottom": bottom, "x0": events_x, "x1": WIDTH - PAD},
        "ticks": ticks,
        "blocks": blocks,
        "empty": not timed,
        "empty_y": (top + bottom) / 2,
        "events_mid": events_x + events_w / 2,
        "column": column,
        "chips": chips,
        "chips_y": HEIGHT - PAD - 30,
        "tz": str(tz),
    }


def _any_waiting(waiting: Waiting) -> bool:
    return waiting.tasks > 0 or waiting.email > 0 or waiting.other > 0


def _block(p: Any, e: CardEvent, colors: dict[str, str]) -> dict[str, Any]:
    fill = {
        "event": colors["event"],
        "partner": colors["partner"],
        "held": "none",
        "travel": colors["travel"],
    }[e.kind]
    edge = {
        "event": colors["event_edge"],
        "partner": colors["partner_edge"],
        "held": colors["held_edge"],
        "travel": colors["event_edge"],
    }[e.kind]
    quiet = e.kind in ("held", "travel")
    block: dict[str, Any] = {
        "x": p.x,
        "y": p.y,
        "width": p.width,
        "height": p.height,
        "fill": fill,
        "edge": edge,
        "dashed": quiet,
        "lines": [],
    }
    inner = p.width - 16
    h = p.height
    if p.beside:  # a sliver: a marker, with the title beside it
        block["width"] = min(p.width, 8.0)
        size = 11.0
        block["lines"].append(
            {
                "x": p.x + 14,
                "y": p.y + h / 2 + size / 3,
                "size": size,
                "bold": False,
                "muted": quiet,
                "text": fit(e.title, size, p.width - 14),
            }
        )
        return block
    if h >= 38:
        detail = span_words(e.start, e.end) + (f" · {e.place}" if e.place else "")
        block["lines"] = [
            {"x": p.x + 8, "y": p.y + 18, "size": 13.5, "bold": not quiet, "muted": quiet,
             "text": fit(e.title, 13.5, inner, bold=not quiet)},
            {"x": p.x + 8, "y": p.y + 34, "size": 11.5, "bold": False, "muted": True,
             "text": fit(detail, 11.5, inner)},
        ]  # fmt: skip
    else:
        size = 13.0 if h >= 20 else 11.0
        title = fit(e.title, size, inner, bold=not quiet)
        y = p.y + h / 2 + size / 3
        block["lines"] = [
            {"x": p.x + 8, "y": y, "size": size, "bold": not quiet, "muted": quiet,
             "text": title},
        ]  # fmt: skip
        after = p.x + 8 + text_width(title, size, not quiet) + 8
        room = p.x + p.width - 8 - after
        if e.kind != "travel" and title == " ".join(e.title.split()) and room > 40:
            detail = span_words(e.start, e.end) + (f" \u00b7 {e.place}" if e.place else "")
            words = fit(detail, 11.5, room)
            if words:
                block["lines"].append(
                    {"x": after, "y": y, "size": 11.5, "bold": False, "muted": True,
                     "text": words}
                )  # fmt: skip
    return block


def _weather_column(
    weather: CardWeather, line: Timeline, x0: float, x1: float, colors: dict[str, str]
) -> dict[str, Any]:
    hours = [h for h in weather.hours if line.start <= h.at < line.end]
    bars = []
    for h in hours:
        if h.chance < 20:
            continue
        y0, y1 = line.y(h.at), line.y(h.at + timedelta(hours=1))
        bars.append(
            {"x": x0, "y": y0 + 1, "width": (x1 - x0) * h.chance / 100, "height": y1 - y0 - 2}
        )
    points: list[tuple[float, float]] = []
    labels = []
    if hours:
        temps = [h.temp for h in hours]
        lo, hi = min(temps), max(temps)
        spread = max(hi - lo, 8.0)  # a flat day stays near the middle

        def x(t: float) -> float:
            return x0 + 14 + (t - (lo + hi - spread) / 2) / spread * (x1 - x0 - 28)

        points = [(x(h.temp), line.y(h.at + timedelta(minutes=30))) for h in hours]
        warm = max(hours, key=lambda h: (h.temp, -h.at.timestamp()))
        cold = min(hours, key=lambda h: (h.temp, h.at.timestamp()))
        for h in (cold, warm) if warm is not cold else (warm,):
            labels.append(
                {
                    "x": max(x(h.temp) - 6, x0 + 24),  # left of the line, anchored at its end
                    "y": line.y(h.at + timedelta(minutes=30)) - 7,
                    "text": degrees(h.temp, weather.units),
                }
            )
    return {
        "x0": x0,
        "x1": x1,
        "head_y": line.top - 8,
        "head": f"°{weather.units} · rain",
        "bars": bars,
        "points": " ".join(f"{px:.1f},{py:.1f}" for px, py in points),
        "labels": labels,
    }


def card_svg(data: DayCardData, counts: str = "dots", theme: str = "light") -> str:
    return write_svg("day_card.svg", **view(data, counts, theme))
