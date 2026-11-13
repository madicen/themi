"""DC8: the weather on request, drawn from its data. Golden SVGs in `tests/golden/pictures/`."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from tests.unit.test_day_card import golden
from themi.drawing.render import to_png
from themi.standard.day_card import CardHour
from themi.standard.weather_card import WeatherCardData, WeatherDay, view, weather_svg, weather_text

TZ = ZoneInfo("America/Los_Angeles")


def hours(day: int, rain_from: int = 99) -> tuple[CardHour, ...]:
    base = datetime(2026, 10, 21 + day, tzinfo=TZ)
    return tuple(
        CardHour(
            base + timedelta(hours=h),
            46 + 12 * max(0.0, 1 - abs(h - 14) / 8),
            80 if rain_from <= h < rain_from + 4 else 0,
            61 if rain_from <= h < rain_from + 4 else 1,
        )
        for h in range(24)
    )


RAINY = WeatherCardData(
    (
        WeatherDay(date(2026, 10, 21), "Today", hours(0, 14), 58, 46,
                   "Rain likely from about 2 pm, high 58°F."),
        WeatherDay(date(2026, 10, 22), "Tomorrow", hours(1), 61, 47),
    ),
    datetime(2026, 10, 21, 9, 20, tzinfo=TZ),
)  # fmt: skip


def test_the_weather_matches_its_golden_files() -> None:
    golden("weather", weather_svg(RAINY))
    golden("weather_dark", weather_svg(RAINY, "dark"))
    assert to_png(weather_svg(RAINY), 1680)[:4] == b"\x89PNG"


def test_now_is_marked_on_today_only() -> None:
    today, tomorrow = view(RAINY)["rows"]
    assert today["now_x"] is not None and tomorrow["now_x"] is None
    evening = WeatherCardData(RAINY.days, datetime(2026, 10, 21, 22, tzinfo=TZ))
    assert view(evening)["rows"][0]["now_x"] is None  # after 9 pm: off the strip


def test_rain_is_bars_and_the_line_is_a_statement() -> None:
    today, tomorrow = view(RAINY)["rows"]
    assert len(today["bars"]) == 4 and tomorrow["bars"] == []
    assert today["icon"] == "rain" and tomorrow["icon"] == "partly-cloudy-day"
    svg = weather_svg(RAINY)
    assert "Rain likely from about 2 pm" in svg
    for advice in ("umbrella", "should", "bring"):
        assert advice not in svg.lower()


def test_the_weather_in_words() -> None:
    assert weather_text(RAINY) == (
        "Today: 58° / 46°. Rain likely from about 2 pm, high 58°F.\nTomorrow: 61° / 47°."
    )
