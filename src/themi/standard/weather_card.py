"""The weather on request (DC8; the Day Card Plan's "Other uses").

Today and tomorrow, each a row: the day's icon, high and low, the noteworthy line when
there is one (WX2, WX3: statements, never advice), and the waking hours (7 am to 9 pm) as a
strip: temperature as a line, the chance of rain or snow as bars, now marked on today's.
"what's the weather?" and `/weather`; without pictures, the same in words.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, tzinfo
from typing import TYPE_CHECKING, Any

from themi import clock
from themi.accounts import Member
from themi.core import keys
from themi.drawing.layout import hour_label
from themi.drawing.svg import write_svg
from themi.drawing.text import fit, wrap
from themi.standard.day_card import THEMES, CardHour, day_icon, degrees
from themi.standard.drawings import DrawingsPreferences

if TYPE_CHECKING:
    from themi.core.services import Services

WIDTH, HEIGHT = 840, 470
PNG_WIDTH = 1680
PAD = 24
FROM, TO = time(7), time(21)  # the waking hours drawn
CAPTION = "The weather, today and tomorrow."
OFF_TEXT = "The weather isn't on here: an admin can turn it on on the Modules page."
NO_FORECAST_TEXT = "There's no forecast to go on just now; Themi will try again within the hour."


@dataclass(frozen=True)
class WeatherDay:
    day: date
    name: str  # "Today", "Tomorrow"
    hours: tuple[CardHour, ...]
    high: float | None
    low: float | None
    line: str | None = None


@dataclass(frozen=True)
class WeatherCardData:
    days: tuple[WeatherDay, ...]
    now: datetime
    units: str = "F"


class WeatherCard:
    def __init__(self, services: Services) -> None:
        self.services = services

    def data(self) -> WeatherCardData | None:
        """None without the weather module or a fresh forecast."""
        weather = self.services.maybe(keys.weather)
        forecast = weather.latest() if weather is not None else None
        if weather is None or forecast is None:
            return None
        tz = weather.tz()
        now = clock.now().astimezone(tz)
        days = []
        for offset, name in ((0, "Today"), (1, "Tomorrow")):
            day = now.date() + timedelta(days=offset)
            found = forecast.day(day)
            start = _at(day, FROM, tz)
            hours = tuple(
                CardHour(h.at, h.temp, h.chance, h.code)
                for h in forecast.hours
                if h.at.astimezone(tz).date() == day
            )
            days.append(
                WeatherDay(
                    day=day,
                    name=name,
                    hours=hours,
                    high=found.high if found else None,
                    low=found.low if found else None,
                    line=weather.line(max(start, now) if offset == 0 else start),
                )
            )
        return WeatherCardData(tuple(days), now, weather.settings.units)

    async def send(self, member: Member) -> bool:
        """The weather as a picture, as a reply; in words when it can't be drawn or the
        channel shows no pictures. True when a picture went."""
        from themi.channels.outbox import Priority

        data = self.data()
        words = weather_text(data) if data is not None else self._why_not()
        drawings = self.services.maybe(keys.drawings)
        if data is not None and drawings is not None:
            theme = self.services.store.preferences(member.id, DrawingsPreferences).picture_theme
            png = await drawings.png(weather_svg(data, theme), PNG_WIDTH)
            if png is not None:
                sent = await self.services.outbox.send_photo(member, png, CAPTION, kind="weather")
                if sent is not None:
                    return True
        await self.services.outbox.send(member, words, priority=Priority.REPLY, kind="weather")
        return False

    def _why_not(self) -> str:
        return OFF_TEXT if self.services.maybe(keys.weather) is None else NO_FORECAST_TEXT


def _at(day: date, at: time, tz: tzinfo | None) -> datetime:
    return datetime(day.year, day.month, day.day, at.hour, at.minute, tzinfo=tz)


# ----- in words ---------------------------------------------------------------------------


def weather_text(data: WeatherCardData) -> str:
    lines = []
    for day in data.days:
        temps = (
            f"{degrees(day.high, data.units)} / {degrees(day.low, data.units)}"
            if day.high is not None and day.low is not None
            else "no forecast yet"
        )
        lines.append(f"{day.name}: {temps}." + (f" {day.line}" if day.line else ""))
    return "\n".join(lines)


# ----- drawing it -------------------------------------------------------------------------


def view(data: WeatherCardData, theme: str = "light") -> dict[str, Any]:
    colors = THEMES[theme]
    rows = []
    x0, x1 = PAD + 190.0, WIDTH - PAD - 20.0
    row_h, gap, top = 180.0, 20.0, 76.0
    for i, day in enumerate(data.days):
        y0 = top + i * (row_h + gap)
        start = _at(day.day, FROM, data.now.tzinfo)
        end = _at(day.day, TO, data.now.tzinfo)
        span = (end - start).total_seconds()

        def x(at: datetime, start: datetime = start, span: float = span) -> float:
            part = (at - start).total_seconds() / span
            return x0 + min(max(part, 0.0), 1.0) * (x1 - x0)

        hours = [h for h in day.hours if start <= h.at < end]
        chart_top, chart_bottom = y0 + 34, y0 + row_h - 26
        bars, points, labels = [], [], []
        if hours:
            temps = [h.temp for h in hours]
            lo, hi = min(temps), max(temps)
            spread = max(hi - lo, 8.0)
            mid = (lo + hi) / 2

            def y(
                t: float,
                mid: float = mid,
                spread: float = spread,
                chart_bottom: float = chart_bottom,
                chart_top: float = chart_top,
            ) -> float:
                return (
                    chart_bottom
                    - 14
                    - (t - (mid - spread / 2)) / spread * (chart_bottom - chart_top - 28)
                )

            for h in hours:
                left, right = x(h.at), x(h.at + timedelta(hours=1))
                if h.chance >= 20:
                    height = (chart_bottom - chart_top) * h.chance / 100
                    bars.append(
                        {"x": left + 1, "y": chart_bottom - height, "width": right - left - 2,
                         "height": height}
                    )  # fmt: skip
                points.append((x(h.at + timedelta(minutes=30)), y(h.temp)))
            for h in hours:
                if h.at.hour % 3 == 1:  # 7 am, 10 am, 1 pm, 4 pm, 7 pm
                    labels.append(
                        {"x": x(h.at + timedelta(minutes=30)), "y": y(h.temp) - 8,
                         "text": degrees(h.temp, data.units)}
                    )  # fmt: skip
        ticks = [
            {"x": x(start + timedelta(hours=k)), "label": hour_label(start + timedelta(hours=k))}
            for k in range(0, 15, 3)
        ]
        now_x = x(data.now) if i == 0 and start <= data.now < end else None
        top_right = None
        if day.high is not None and day.low is not None:
            top_right = {
                "high": degrees(day.high, data.units),
                "low": degrees(day.low, data.units),
            }
        rows.append(
            {
                "y": y0,
                "height": row_h,
                "name": day.name,
                "date": f"{day.day:%a} {day.day.day} {day.day:%b}",
                "icon": day_icon(day.hours, start, end) if day.hours else None,
                "temps": top_right,
                "line": fit(day.line, 13, x0 - PAD - 16) if day.line else None,
                "line_more": None,
                "chart_top": chart_top,
                "chart_bottom": chart_bottom,
                "bars": bars,
                "points": " ".join(f"{px:.1f},{py:.1f}" for px, py in points),
                "labels": labels,
                "ticks": ticks,
                "now_x": now_x,
            }
        )
        if day.line and rows[-1]["line"] != day.line:  # a long line: two lines
            first, *rest = wrap(day.line, 13, x0 - PAD - 16, 2) or [""]
            rows[-1]["line"], rows[-1]["line_more"] = first, rest[0] if rest else None
    return {
        "width": WIDTH,
        "height": HEIGHT,
        "pad": PAD,
        "c": colors,
        "title": "The weather",
        "head": f"°{data.units} · chance of rain or snow",
        "x0": x0,
        "x1": x1,
        "rows": rows,
    }


def weather_svg(data: WeatherCardData, theme: str = "light") -> str:
    return write_svg("weather_card.svg", **view(data, theme))
