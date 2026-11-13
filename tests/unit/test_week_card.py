"""DC6: the week ahead, drawn from its data. Golden SVGs in `tests/golden/pictures/`."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from tests.unit.test_day_card import golden
from themi.drawing.render import to_png
from themi.standard.day_card import ICONS, CardEvent
from themi.standard.week_card import (
    NOTHING_TEXT,
    WeekCardData,
    WeekDay,
    view,
    week_svg,
    week_text,
)

TZ = ZoneInfo("America/Los_Angeles")
FIRST = date(2026, 10, 21)


def at(day: int, hour: float) -> datetime:
    return datetime(2026, 10, 21 + day, tzinfo=TZ) + timedelta(hours=hour)


EVENTS = {
    0: [
        CardEvent("a", "Standup", at(0, 9), at(0, 9.5)),
        CardEvent("b", "Dentist", at(0, 14), at(0, 15), place="Smile Dental"),
        CardEvent("c", "Soccer pickup", at(0, 15.5), at(0, 16.5)),
        CardEvent("d", "Call with Sam (Erin)", at(0, 16), at(0, 17), kind="partner"),
    ],
    1: [
        CardEvent("e", "School holiday", at(1, 0), at(2, 0), all_day=True),
        CardEvent("f", "Call the vet", at(1, 10), at(1, 12), kind="held"),
    ],
    3: [CardEvent("g", "Parent-teacher conference", at(3, 18), at(3, 19))],
    5: [
        CardEvent("h", "Farmers market", at(5, 9), at(5, 11)),
        CardEvent("i", "Birthday party at the park", at(5, 13), at(5, 16)),
    ],
}
CODES = [1, 61, 3, 0, 80, 71, 95]
WEEK = WeekCardData(
    "Erin",
    FIRST,
    tuple(
        WeekDay(
            FIRST + timedelta(days=i), tuple(EVENTS.get(i, [])), 58 + i, 44 + i, ICONS[CODES[i]]
        )
        for i in range(7)
    ),
)
QUIET = WeekCardData("Erin", FIRST, tuple(WeekDay(FIRST + timedelta(days=i)) for i in range(7)))


def test_the_week_matches_its_golden_files() -> None:
    golden("week", week_svg(WEEK))
    golden("week_dark", week_svg(WEEK, "dark"))
    golden("week_quiet", week_svg(QUIET))
    png = to_png(week_svg(WEEK), 1680)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_every_day_has_its_column_and_today_is_marked() -> None:
    shown = view(WEEK)
    assert [c["name"] + " " + c["date"] for c in shown["columns"]] == [
        "Wed 21", "Thu 22", "Fri 23", "Sat 24", "Sun 25", "Mon 26", "Tue 27",
    ]  # fmt: skip
    assert [c["today"] for c in shown["columns"]] == [True] + [False] * 6
    assert shown["subtitle"] == "Erin · Wed 21 Oct to Tue 27 Oct"
    assert shown["columns"][1]["strip"] == "School holiday"
    assert shown["columns"][0]["weather"] == {"icon": "partly-cloudy-day", "text": "58° / 44°"}


def test_the_hours_widen_for_an_early_or_late_event() -> None:
    early = WeekCardData(
        "Erin", FIRST, (WeekDay(FIRST, (CardEvent("x", "Gym", at(0, 6), at(0, 7)),)),)
    )
    ticks = view(early)["ticks"]
    assert ticks[0]["label"] == "6 am"
    assert view(WEEK)["ticks"][0]["label"] == "8 am"


def test_without_weather_the_columns_have_no_forecast() -> None:
    assert all(c["weather"] is None for c in view(QUIET)["columns"])
    assert view(QUIET)["empty"]


def test_the_week_in_words_for_a_channel_without_pictures() -> None:
    assert week_text(WEEK).splitlines() == [
        "The week ahead:",
        "- Wed 21: 9 am Standup; 2 pm Dentist; 3:30 pm Soccer pickup; 4 pm Call with Sam (Erin)",
        "- Thu 22: School holiday; 10 am Call the vet",
        "- Sat 24: 6 pm Parent-teacher conference",
        "- Mon 26: 9 am Farmers market; 1 pm Birthday party at the park",
    ]
    assert week_text(QUIET) == NOTHING_TEXT
