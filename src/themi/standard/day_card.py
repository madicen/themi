"""The day card: a picture of someone's day (DC3, laid out for a glance in DC13; the plan's
"What the family sees").

Today's events at their times, the weather, and a quiet sign of what's waiting behind the
morning message's buttons. Drawn from Themi's own data by `themi.drawing`; sent with the
morning message (DC5) and shown on the website (DC7).

- A weather panel: the day's icon, the high, the low and the noteworthy line (WX2); amber
  for an NWS alert (WX3). Never advice, never energy.
- Events are the morning message's (their own and their partner's shared ones), plus the
  blocks Themi holds for tasks ("task-block:"), drawn dashed. A task's own copy ("task:")
  isn't drawn: it's a task, not a plan for the day. Each is a bar in a thin lane, with its
  label to the right on a leader line, so titles get the card's width.
- An event with a place gets a lead line before its bar and "leave 1:20" in its label,
  from the rough drive time (places already found, no lookup, no traffic: a picture never
  waits on the network).
- Rain or snow likely (40%+) is a strip beside the hours.
- What's waiting is three-dot meters by default (`picture_counts`), never red, never
  "overdue", never words like "High".
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
from themi.drawing.layout import BLOCK_MIN, Span, Timeline, all_day_rows, columns, window
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
        "panel": "#FFFFFF",
        "track": "#ECEAE4",
        "wet": "#4A88C7",
        "meter_tasks": "#3F8F6B",
        "meter_email": "#C07A4E",
        "meter_other": "#8569BF",
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
        "panel": "#1F2227",
        "track": "#2A2E35",
        "wet": "#5AA0E6",
        "meter_tasks": "#5DB48C",
        "meter_email": "#E09A6E",
        "meter_other": "#A68BE0",
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


def meter_dots(count: int) -> int:
    """How many of a meter's three dots are filled: none, one, two (up to 3), three."""
    return 0 if count <= 0 else 1 if count <= 1 else 2 if count <= 3 else 3


def meter_words(label: str, count: int, counts: str) -> str:
    """The words under a meter: the tray's name, and its count only for `numbers`."""
    return f"{label} {count}" if counts == "numbers" else label


LANE_W, LANE_GAP = 12.0, 6.0
LABEL_TWO, LABEL_ONE = 34.0, 18.0  # a label's height, in two lines or one
LABEL_GAP_TWO, LABEL_GAP_ONE = 4.0, 2.0
PLATE_H = 64.0
WET = 40  # % chance of rain or snow drawn beside the hours


def view(data: DayCardData, counts: str = "dots", theme: str = "light") -> dict[str, Any]:
    """Every position and word on the card, for the template (DC13's layout)."""
    colors = THEMES[theme]
    tz = data.start.tzinfo
    timed = [e for e in data.events if not e.all_day]
    travel = [e for e in timed if e.kind == "travel"]
    timed = [e for e in timed if e.kind != "travel"]
    all_day = [e for e in data.events if e.all_day]
    spans = [Span(e.key, e.start, e.end) for e in timed]
    w_start, w_end = window(data.start, spans + [Span(t.key, t.start, t.end) for t in travel])

    header = {
        "name": f"{data.name.upper()}\u2019S DAY",
        "weekday": f"{data.day:%A}",
        "date": f"{data.day.day} {data.day:%B}",
    }
    y = 92.0
    weather = data.weather
    panel: dict[str, Any] | None = None
    if weather is not None and weather.high is not None and weather.low is not None:
        line_words = weather.line or ""
        panel = {
            "y": y,
            "height": 100.0 if line_words else 66.0,
            "fill": colors["alert"] if weather.alert else colors["note"],
            "edge": colors["alert_edge"] if weather.alert else "",
            "icon": day_icon(weather.hours, w_start, w_end),
            "high": degrees(weather.high, weather.units),
            "low": degrees(weather.low, weather.units),
            "line": fit(line_words, 14, WIDTH - 2 * PAD - 32, bold=weather.alert),
            "alert": weather.alert,
        }
        y += panel["height"] + 16

    cols = columns(spans)
    lane_count = max((n for _, n in cols.values()), default=1)
    calendar = {"head_y": y + 18, "summary": _summary(timed, cols)}
    y += 32

    strip = []
    shown, more = all_day_rows([e.key for e in all_day])
    for key in shown:
        e = next(a for a in all_day if a.key == key)
        suffix = f"  +{more} more" if key == shown[-1] and more else ""
        room = WIDTH - 2 * PAD - 24 - text_width("All day  ", 12.5, True) - text_width(suffix, 12)
        strip.append(
            {
                "y": y,
                "title": fit(e.title, 12.5, room),
                "more": suffix.strip(),
                "fill": colors["partner" if e.kind == "partner" else "event"],
            }
        )
        y += 30

    waiting = counts != "hide" and _any_waiting(data.waiting)
    top = y + 14
    bottom = HEIGHT - PAD - (PLATE_H + 18 if waiting else 0) - 8
    line = Timeline(w_start, w_end, top=top, height=bottom - top)
    lanes_x0 = PAD + 58
    lanes = [lanes_x0 + i * (LANE_W + LANE_GAP) for i in range(lane_count)]
    lanes_x1 = lanes[-1] + LANE_W
    elbow = lanes_x1 + 12
    labels_x = elbow + 16

    bars, wanted = [], []
    for e in sorted(timed, key=lambda e: (e.start, e.key)):
        x = lanes[cols[e.key][0]]
        y0 = max(line.y(e.start), top)
        y1 = min(line.y(e.end), bottom)
        height = max(y1 - y0, BLOCK_MIN)
        color = colors[
            {"event": "event_edge", "partner": "partner_edge", "held": "held_edge"}[e.kind]
        ]
        detail = span_words(e.start, e.end) + (f" · {e.place}" if e.place else "")
        lead = None
        leave = next((t for t in travel if t.end == e.start), None)
        if leave is not None:
            lead_y = max(line.y(leave.start), top)
            lead = {"y": lead_y, "height": max(y0 - lead_y - 2, 0)}
            detail += f" · leave {clock_words(leave.start)}"
        if e.kind == "held":
            detail = span_words(e.start, e.end) + " · time for it"
        bars.append(
            {"x": x, "y": y0, "height": height, "color": color, "held": e.kind == "held",
             "lead": lead}
        )  # fmt: skip
        wanted.append((y0 + height / 2, x + LANE_W, color, e, detail))

    two = len(wanted) * (LABEL_TWO + LABEL_GAP_TWO) <= bottom - top + 12
    tops = spread([w[0] for w in wanted], two, top - 6, bottom + 6)
    text_w = WIDTH - PAD - labels_x
    labels = []
    for (anchor, bar_right, color, e, detail), label_y in zip(wanted, tops, strict=True):
        quiet = e.kind == "held"
        mid = label_y + 9
        if two:
            title = fit(e.title, 14, text_w, bold=not quiet)
            beside = ""
            under = fit(detail, 11.5, text_w)
        else:
            title = fit(e.title, 14, text_w * 0.62, bold=not quiet)
            beside = fit(span_words(e.start, e.end), 11.5,
                         text_w - text_width(title, 14, not quiet) - 8)  # fmt: skip
            under = ""
        points = [(bar_right, anchor), (elbow, anchor), (elbow, mid), (labels_x - 6, mid)]
        labels.append(
            {
                "y": label_y,
                "title": title,
                "beside": beside,
                "beside_x": labels_x + text_width(title, 14, not quiet) + 8,
                "detail": under,
                "quiet": quiet,
                "color": color,
                "leader": " ".join(f"{px:.1f},{py:.1f}" for px, py in points),
            }
        )

    wet: list[dict[str, float]] = []
    wet_icon = None
    if weather is not None:
        hours = [h for h in weather.hours if w_start <= h.at < w_end and h.chance >= WET]
        runs: list[list[CardHour]] = []
        for h in hours:  # hours in a row are one strip, as likely as its likeliest hour
            if runs and runs[-1][-1].at + timedelta(hours=1) == h.at:
                runs[-1].append(h)
            else:
                runs.append([h])
        for run in runs:
            y0, y1 = line.y(run[0].at), line.y(run[-1].at + timedelta(hours=1))
            chance = max(h.chance for h in run)
            wet.append({"y": y0, "height": y1 - y0, "opacity": 0.35 + 0.65 * chance / 100})
        if hours:
            snowy = hours[0].code in (71, 73, 75, 77, 85, 86)
            wet_icon = {"y": line.y(hours[0].at), "icon": "snow" if snowy else "rain"}

    plate = None
    if waiting:
        plate_y = HEIGHT - PAD - PLATE_H
        col_w = (WIDTH - 2 * PAD - 32) / 3
        meters = []
        for i, (label, count, key) in enumerate(
            (
                ("Tasks", data.waiting.tasks, "tasks"),
                ("Email", data.waiting.email, "email"),
                ("Everything else", data.waiting.other, "other"),
            )
        ):
            x = PAD + 16 + i * col_w
            lit = meter_dots(count)
            meters.append(
                {
                    "x": x,
                    "words": meter_words(label, count, counts),
                    "dots": [
                        {"x": x + 6.5 + k * 19, "fill": colors[f"meter_{key}"] if k < lit
                         else colors["track"]}
                        for k in range(3)
                    ],
                }
            )  # fmt: skip
        plate = {"y": plate_y, "height": PLATE_H, "meters": meters}

    return {
        "width": WIDTH,
        "height": HEIGHT,
        "pad": PAD,
        "c": colors,
        "header": header,
        "panel": panel,
        "calendar": calendar,
        "strip": strip,
        "timeline": {"top": top, "bottom": bottom},
        "ticks": [{"y": t.y, "label": t.label} for t in line.ticks()],
        "lanes": lanes,
        "lane_w": LANE_W,
        "lane_top": top - 6,
        "lane_height": bottom - top + 12,
        "bars": bars,
        "labels": labels,
        "labels_x": labels_x,
        "two_lines": two,
        "wet": wet,
        "wet_icon": wet_icon,
        "empty": not timed,
        "empty_y": (top + bottom) / 2,
        "plate": plate,
        "tz": str(tz),
    }


def spread(anchors: Sequence[float], two: bool, top: float, bottom: float) -> list[float]:
    """Each label's top: as near its event as it can be, never overlapping the one before,
    and all of them between `top` and `bottom`. `anchors` in order, top to bottom."""
    height, gap = (LABEL_TWO, LABEL_GAP_TWO) if two else (LABEL_ONE, LABEL_GAP_ONE)
    lift = height / 2 if two else 9
    tops: list[float] = []
    for anchor in anchors:
        least = tops[-1] + height + gap if tops else top
        tops.append(max(anchor - lift, least))
    if len(anchors) * (height + gap) - gap > bottom - top:  # more than fit: evenly
        step = (bottom - top - height) / max(len(anchors) - 1, 1)
        return [top + i * step for i in range(len(anchors))]
    limit = bottom - height
    for i in range(len(tops) - 1, -1, -1):
        tops[i] = min(tops[i], limit)
        limit = tops[i] - height - gap
    return tops


def _summary(timed: Sequence[CardEvent], cols: dict[str, tuple[int, int]]) -> str:
    """ "6 events · 1 held for a task · 1 overlap": counted, never graded."""
    if not timed:
        return ""
    held = sum(1 for e in timed if e.kind == "held")
    events = len(timed) - held
    overlaps = sum(1 for e in timed if cols[e.key][0] > 0)
    words = [f"{events} event{'' if events == 1 else 's'}"]
    if held:
        words.append(f"{held} held for {'a task' if held == 1 else 'tasks'}")
    if overlaps:
        words.append(f"{overlaps} overlap{'' if overlaps == 1 else 's'}")
    return " · ".join(words)


def _any_waiting(waiting: Waiting) -> bool:
    return waiting.tasks > 0 or waiting.email > 0 or waiting.other > 0


def card_svg(data: DayCardData, counts: str = "dots", theme: str = "light") -> str:
    return write_svg("day_card.svg", **view(data, counts, theme))
