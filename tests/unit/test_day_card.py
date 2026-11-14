"""DC3 and DC13: the day card, drawn from its data. Golden SVGs in `tests/golden/pictures/` (`make
golden`, or THEMI_WRITE_GOLDEN=1, writes them again)."""

from __future__ import annotations

import itertools
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given
from hypothesis import strategies as st

from themi.drawing.render import to_png
from themi.standard.day_card import (
    CardEvent,
    CardHour,
    CardWeather,
    DayCardData,
    Waiting,
    card_svg,
    day_icon,
    degrees,
    meter_dots,
    meter_words,
    span_words,
    spread,
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
    for words in ("Wednesday", "21 October", "ERIN\u2019S DAY", "Standup", "Dentist",
                  "2\u20133 pm · Smile Dental · leave 1:20", "School holiday",
                  "Call with Sam (Erin)", "Pills", "Rain likely from about 2 pm",
                  "58°", "low 46°", "Your calendar"):  # fmt: skip
        assert words in svg, words
    assert "Dinner with the Parks at their place downtown on Elm Street" not in svg
    assert "Dinner with the Parks" in svg  # shortened to fit, with an ellipsis
    assert "…" in svg


def test_the_calendar_heading_counts_events_holds_and_overlaps() -> None:
    assert view(BUSY)["calendar"]["summary"] == "6 events · 1 held for a task · 1 overlap"
    assert view(STORM)["calendar"]["summary"] == "1 event"
    assert view(EMPTY)["calendar"]["summary"] == ""


def test_travel_is_a_lead_in_on_its_event_not_a_block_of_its_own() -> None:
    shown = view(BUSY)
    assert len(shown["bars"]) == 7  # eight timed entries, less the travel
    assert sum(1 for b in shown["bars"] if b["lead"]) == 1
    assert "Leave around" not in card_svg(BUSY)


def test_no_energy_and_no_red_for_what_waits() -> None:
    svg = card_svg(BUSY, "numbers")
    assert "energy" not in svg.lower()
    assert "overdue" not in svg.lower()
    assert "Tasks 4" in svg and "Email 1" in svg and "Everything else 2" in svg
    for words in ("High", "Medium", "Low"):
        assert f">{words}<" not in card_svg(BUSY)
    for color in ("#FF0000", "#F00", "red"):
        assert f'"{color}"' not in svg


def test_hidden_counts_leave_no_footer() -> None:
    plain = view(BUSY, "dots")
    hidden = view(BUSY, "hide")
    assert plain["plate"] and not hidden["plate"]
    assert hidden["timeline"]["bottom"] > plain["timeline"]["bottom"]  # more room for the day


def test_an_empty_day_says_so_and_keeps_the_weather() -> None:
    svg = card_svg(EMPTY)
    assert "Nothing on the calendar" in svg
    assert view(EMPTY)["panel"]["high"] == "58°"
    assert view(EMPTY)["plate"] is None  # nothing waiting: no meters


def test_an_alert_is_an_amber_panel_and_a_note_is_quiet() -> None:
    assert view(STORM)["panel"]["fill"] == "#FFF1D6"
    assert view(STORM)["panel"]["alert"]
    assert view(BUSY)["panel"]["fill"] == "#EEF0F3"
    assert view(EMPTY)["panel"]["line"] == ""


def test_rain_and_snow_sit_beside_their_hours() -> None:
    busy = view(BUSY)
    assert len(busy["wet"]) == 1 and busy["wet_icon"]["icon"] == "rain"
    assert view(STORM)["wet_icon"]["icon"] == "snow"
    assert view(EMPTY)["wet"] == [] and view(EMPTY)["wet_icon"] is None


def test_without_the_weather_module_there_is_no_panel_or_rain() -> None:
    plain = DayCardData("Erin", date(2026, 10, 21), at(7), BUSY.events)
    shown = view(plain)
    assert shown["panel"] is None and shown["wet"] == []
    assert len(shown["labels"]) == 7


def test_long_titles_stay_on_the_card() -> None:
    from themi.drawing.text import text_width

    shown = view(BUSY)
    for label in shown["labels"]:
        assert shown["labels_x"] + text_width(label["title"], 14, True) <= 540 - 28 + 1
        assert shown["labels_x"] + text_width(label["detail"], 11.5) <= 540 - 28 + 1


def test_a_crowded_day_has_one_line_labels_with_their_times() -> None:
    crowded = DayCardData(
        "Michael",
        date(2026, 10, 21),
        at(7),
        tuple(CardEvent(str(i), f"Thing {i}", at(7 + i), at(7.5 + i)) for i in range(13)),
        BUSY.weather,
        Waiting(tasks=2),
    )
    shown = view(crowded)
    assert not shown["two_lines"]
    assert shown["labels"][0]["beside"] == "7\u20137:30 am"
    assert view(BUSY)["two_lines"]


def test_overlapping_events_take_side_by_side_lanes() -> None:
    shown = view(BUSY)
    assert len(shown["lanes"]) == 2
    second = [b for b in shown["bars"] if b["x"] == shown["lanes"][1]]
    assert len(second) == 1 and second[0]["color"] == "#8569BF"  # Sam's call, beside soccer


@given(st.lists(st.floats(min_value=150, max_value=600), min_size=1, max_size=30))
def test_labels_never_overlap_and_stay_on_the_timeline(anchors: list[float]) -> None:
    anchors.sort()
    for two in (True, False):
        tops = spread(anchors, two, 140.0, 600.0)
        height = 34.0 if two else 18.0
        assert all(t >= 140.0 - 0.01 and t + height <= 600.0 + 0.01 for t in tops)
        fits = len(anchors) * (height + (4 if two else 2)) - (4 if two else 2) <= 460
        if fits:
            assert all(b - a >= height - 0.01 for a, b in itertools.pairwise(tops))


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


def test_waiting_meters_in_dots_or_numbers() -> None:
    assert [meter_dots(n) for n in (0, 1, 2, 3, 4, 9)] == [0, 1, 2, 2, 3, 3]
    assert meter_words("Tasks", 9, "dots") == "Tasks"
    assert meter_words("Email", 1, "numbers") == "Email 1"
