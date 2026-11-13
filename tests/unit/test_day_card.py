"""DC3: the day card, drawn from its data. Golden SVGs in `tests/golden/pictures/` (`make
golden`, or THEMI_WRITE_GOLDEN=1, writes them again)."""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from themi.drawing.render import to_png
from themi.standard.day_card import (
    CardEvent,
    CardHour,
    CardWeather,
    DayCardData,
    Waiting,
    card_svg,
    chip_words,
    day_icon,
    degrees,
    span_words,
    view,
)

GOLDEN = Path(__file__).resolve().parents[1] / "golden" / "pictures"
WRITE = os.environ.get("THEMI_WRITE_GOLDEN") == "1"
TZ = ZoneInfo("America/Los_Angeles")
DAY = datetime(2026, 10, 21, tzinfo=TZ)


def at(hour: float) -> datetime:
    return DAY + timedelta(hours=hour)


def hours(rain_from: int | None = None, code: int = 61) -> tuple[CardHour, ...]:
    out = []
    for h in range(24):
        wet = rain_from is not None and rain_from <= h < rain_from + 4
        out.append(
            CardHour(at(h), 46 + 12 * max(0.0, 1 - abs(h - 14) / 8), 80 if wet else 0,
                     code if wet else (1 if 7 <= h < 17 else 0))
        )  # fmt: skip
    return tuple(out)


BUSY = DayCardData(
    name="Erin",
    day=date(2026, 10, 21),
    start=at(7.25),
    events=(
        CardEvent("a", "School holiday", DAY, DAY + timedelta(days=1), all_day=True),
        CardEvent("b", "Standup", at(9), at(9.5)),
        CardEvent("c", "Call the vet", at(10.5), at(12), kind="held"),
        CardEvent("t", "Leave around 1:20", at(13 + 1 / 3), at(14), kind="travel"),
        CardEvent("d", "Dentist", at(14), at(15), place="Smile Dental"),
        CardEvent("e", "Soccer pickup", at(15.5), at(16.5)),
        CardEvent("f", "Call with Sam (Erin)", at(16), at(17), kind="partner"),
        CardEvent("g", "Pills", at(17.5), at(17.5 + 10 / 60)),
        CardEvent(
            "h",
            "Dinner with the Parks at their place downtown on Elm Street",
            at(18),
            at(19.5),
            place="The Parks' house",
        ),
    ),
    weather=CardWeather(hours(14), 58, 46, "F", "Rain likely from about 2 pm, high 58°F."),
    waiting=Waiting(tasks=4, email=1, other=2),
)
EMPTY = DayCardData(
    name="Erin",
    day=date(2026, 10, 21),
    start=at(7.25),
    weather=CardWeather(hours(), 58, 46, "F"),
)
STORM = DayCardData(
    name="Michael",
    day=date(2026, 10, 21),
    start=at(6.5),
    events=(CardEvent("a", "Dentist", at(10), at(11), place="Smile Dental"),),
    weather=CardWeather(hours(17, code=71), 34, 22, "F", "Winter Storm Warning from 6 pm.", True),
    waiting=Waiting(email=3),
)


def golden(name: str, svg: str) -> None:
    path = GOLDEN / f"{name}.svg"
    if WRITE:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(svg)
    assert path.exists(), f"{path} is missing: make golden"
    assert svg == path.read_text(), f"{name}.svg changed (make golden writes it again)"


@pytest.mark.parametrize(
    ("name", "data", "counts", "theme"),
    [
        ("busy", BUSY, "dots", "light"),
        ("busy_dark", BUSY, "dots", "dark"),
        ("busy_numbers", BUSY, "numbers", "light"),
        ("busy_hidden", BUSY, "hide", "light"),
        ("empty", EMPTY, "dots", "light"),
        ("storm", STORM, "dots", "light"),
    ],
)
def test_the_card_matches_its_golden_file(
    name: str, data: DayCardData, counts: str, theme: str
) -> None:
    svg = card_svg(data, counts, theme)
    golden(name, svg)
    png = to_png(svg, 1080)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_every_event_and_the_weather_are_on_the_busy_card() -> None:
    svg = card_svg(BUSY)
    for words in ("Wednesday 21 October", "Erin\u2019s day", "Standup", "Dentist",
                  "2\u20133 pm · Smile Dental", "Leave around 1:20", "School holiday",
                  "Call with Sam (Erin)", "Pills", "Rain likely from about 2 pm",
                  "58°", "low 46°"):  # fmt: skip
        assert words in svg, words
    assert "Dinner with the Parks at their place downtown on Elm Street" not in svg
    assert "Dinner with the Parks" in svg  # shortened to fit, with an ellipsis
    assert "…" in svg


def test_no_energy_and_no_red_for_what_waits() -> None:
    svg = card_svg(BUSY, "numbers")
    assert "energy" not in svg.lower()
    assert "overdue" not in svg.lower()
    assert "4 tasks" in svg and "1 email" in svg and "2 other things" in svg
    for color in ("#FF0000", "#F00", "red"):
        assert f'"{color}"' not in svg


def test_hidden_counts_leave_no_footer() -> None:
    plain = view(BUSY, "dots")
    hidden = view(BUSY, "hide")
    assert plain["chips"] and not hidden["chips"]
    assert hidden["timeline"]["bottom"] > plain["timeline"]["bottom"]  # more room for the day


def test_an_empty_day_says_so_and_keeps_the_weather() -> None:
    svg = card_svg(EMPTY)
    assert "Nothing on the calendar" in svg
    assert "<polyline" in svg
    assert view(EMPTY)["chips"] == []


def test_an_alert_is_a_warning_band_and_a_note_is_quiet() -> None:
    assert view(STORM)["band"]["fill"] == "#FFF1D6"
    assert view(BUSY)["band"]["fill"] == "#EEF0F3"
    assert view(EMPTY)["band"] is None


def test_without_the_weather_module_the_events_take_the_width() -> None:
    plain = DayCardData("Erin", date(2026, 10, 21), at(7), BUSY.events)
    shown = view(plain)
    assert shown["column"] is None and shown["top_right"] is None and shown["band"] is None
    assert max(b["x"] + b["width"] for b in shown["blocks"]) > 480


def test_long_titles_stay_inside_their_blocks() -> None:
    from themi.drawing.text import text_width

    for block in view(BUSY)["blocks"]:
        for line in block["lines"]:
            width = text_width(line["text"], line["size"], line["bold"])
            right = block["x"] + 8 + width if not line["x"] > block["x"] + 10 else line["x"] + width
            assert right <= 540 - 28 + 1, line["text"]


# ----- the small parts --------------------------------------------------------------------


def test_time_spans_read_like_the_message() -> None:
    assert span_words(at(14), at(15)) == "2\u20133 pm"
    assert span_words(at(10.5), at(12.25)) == "10:30 am\u201312:15 pm"
    assert span_words(at(12), at(13)) == "noon\u20131 pm"
    assert span_words(at(10.5), at(12)) == "10:30 am\u2013noon"


def test_degrees_in_either_unit() -> None:
    assert degrees(58.4, "F") == "58°"
    assert degrees(32, "C") == "0°"


def test_the_days_icon_is_the_gravest_weather_that_lasts() -> None:
    assert day_icon(hours(14), at(7), at(21)) == "rain"
    assert day_icon(hours(), at(7), at(21)) == "partly-cloudy-day"
    one_shower = tuple(
        CardHour(h.at, h.temp, h.chance, 80 if h.at == at(12) else h.code) for h in hours()
    )
    assert day_icon(one_shower, at(7), at(21)) == "partly-cloudy-day"  # an hour isn't the day
    storm = tuple(CardHour(h.at, h.temp, h.chance, 95 if 15 <= h.at.hour < 17 else 61)
                  for h in hours())  # fmt: skip
    assert day_icon(storm, at(7), at(21)) == "thunderstorms-rain"


def test_waiting_chips_in_dots_or_numbers() -> None:
    assert chip_words("Tasks", 1, "dots", "task", "tasks") == "Tasks •"
    assert chip_words("Tasks", 3, "dots", "task", "tasks") == "Tasks ••"
    assert chip_words("Tasks", 9, "dots", "task", "tasks") == "Tasks •••"
    assert chip_words("Email", 1, "numbers", "email", "emails") == "1 email"
