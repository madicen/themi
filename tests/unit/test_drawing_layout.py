"""DC2: the day's timeline: the window, columns for overlaps, short blocks, all-day rows."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from hypothesis import given, settings
from hypothesis import strategies as st

from themi.drawing.layout import (
    BLOCK_MIN,
    Span,
    Timeline,
    all_day_rows,
    columns,
    hour_label,
    place,
    window,
)

TZ = ZoneInfo("America/Los_Angeles")
DAY = datetime(2026, 10, 21, tzinfo=TZ)


def at(hour: float) -> datetime:
    return DAY + timedelta(hours=hour)


def span(key: str, start: float, end: float) -> Span:
    return Span(key, at(start), at(end))


# ----- the window ---------------------------------------------------------------------


def test_the_window_runs_from_the_morning_time_to_9_pm() -> None:
    assert window(at(7.25), [span("a", 10, 11)]) == (at(7), at(21))


def test_an_earlier_event_opens_the_window_earlier() -> None:
    assert window(at(8), [span("gym", 6.5, 7.5)]) == (at(6), at(21))


def test_an_evening_event_keeps_the_window_open() -> None:
    assert window(at(8), [span("show", 20, 22.5)]) == (at(8), at(23))


def test_the_window_stays_inside_the_day() -> None:
    late = Span("flight", at(22), at(27))  # into tomorrow
    early = Span("red-eye", at(-3), at(2))  # from yesterday
    assert window(at(8), [late, early]) == (at(0), at(24))


def test_a_morning_time_after_9_pm_still_has_an_hour() -> None:
    assert window(at(21.5), []) == (at(21), at(22))


# ----- the timeline -------------------------------------------------------------------


def test_minutes_become_y_inside_the_timeline() -> None:
    line = Timeline(at(8), at(20), top=100, height=600)
    assert line.y(at(8)) == 100
    assert line.y(at(14)) == 400
    assert line.y(at(20)) == 700
    assert line.y(at(6)) == 100  # before: held at the top
    assert line.y(at(23)) == 700


def test_ticks_every_hour_on_a_short_day_and_every_two_on_a_long_one() -> None:
    short = Timeline(at(14), at(21), 0, 700).ticks()
    assert [t.label for t in short] == [
        "2 pm",
        "3 pm",
        "4 pm",
        "5 pm",
        "6 pm",
        "7 pm",
        "8 pm",
        "9 pm",
    ]
    long = Timeline(at(7), at(21), 0, 700).ticks()
    assert [t.label for t in long] == [
        "7 am",
        "9 am",
        "11 am",
        "1 pm",
        "3 pm",
        "5 pm",
        "7 pm",
        "9 pm",
    ]
    assert long[0].y == 0 and long[-1].y == 700


def test_hour_labels() -> None:
    assert hour_label(at(0)) == "midnight"
    assert hour_label(at(12)) == "noon"
    assert hour_label(at(9.5)) == "9:30 am"
    assert hour_label(at(13)) == "1 pm"


# ----- columns ------------------------------------------------------------------------


def test_events_that_dont_overlap_take_the_whole_width() -> None:
    cols = columns([span("a", 9, 10), span("b", 10, 11), span("c", 13, 14)])
    assert cols == {"a": (0, 1), "b": (0, 1), "c": (0, 1)}


def test_two_overlapping_events_sit_side_by_side() -> None:
    cols = columns([span("soccer", 15.5, 16.5), span("call", 16, 17)])
    assert cols == {"soccer": (0, 2), "call": (1, 2)}


def test_three_at_once_make_three_columns_and_a_freed_column_is_reused() -> None:
    cols = columns(
        [span("a", 9, 12), span("b", 9.5, 10), span("c", 9.75, 11), span("d", 10.5, 11.5)]
    )
    assert cols["a"] == (0, 3)
    assert cols["b"] == (1, 3)
    assert cols["c"] == (2, 3)
    assert cols["d"] == (1, 3)  # b's column, free from 10


def test_a_new_cluster_starts_wide_again() -> None:
    cols = columns([span("a", 9, 10), span("b", 9, 10), span("c", 14, 15)])
    assert cols["c"] == (0, 1)


# ----- blocks -------------------------------------------------------------------------


LINE = Timeline(at(8), at(21), top=200, height=780)  # 60 px an hour


def test_a_block_runs_from_its_start_to_its_end() -> None:
    (dentist,) = place([span("dentist", 14, 15)], LINE, left=100, width=400)
    assert (dentist.x, dentist.y, dentist.width, dentist.height) == (100, 560, 400, 60)
    assert not dentist.beside


def test_overlapping_blocks_split_the_width_with_a_gap() -> None:
    soccer, call = place([span("soccer", 15.5, 16.5), span("call", 16, 17)], LINE, 100, 404)
    assert soccer.width == call.width == 200
    assert call.x == soccer.x + 204


def test_a_ten_minute_event_has_its_title_beside_it() -> None:
    (quick,) = place([span("pills", 9, 9 + 10 / 60)], LINE, 100, 400)
    assert quick.beside
    assert quick.height == 10


def test_a_five_minute_event_is_still_seen() -> None:
    (blip,) = place([span("call", 9, 9 + 1 / 60)], LINE, 100, 400)
    assert blip.height == BLOCK_MIN


def test_events_crossing_the_window_are_clipped_and_marked() -> None:
    early, late = place([span("gym", 7, 9), span("show", 20, 23)], LINE, 100, 400)
    assert (early.y, early.height, early.clipped_top) == (200, 60, True)
    assert late.clipped_bottom and late.y + late.height == LINE.bottom


def test_an_event_wholly_outside_isnt_placed() -> None:
    assert place([span("yesterday", -5, -4)], LINE, 100, 400) == []


def test_a_full_day_of_twelve_events() -> None:
    spans = [span(f"e{i}", 8 + i, 8.75 + i) for i in range(12)]
    placed = place(spans, LINE, 100, 400)
    assert len(placed) == 12
    assert all(p.columns == 1 for p in placed)


# ----- all-day ------------------------------------------------------------------------


def test_all_day_events_fill_two_rows_then_count_the_rest() -> None:
    assert all_day_rows(["holiday"]) == (["holiday"], 0)
    assert all_day_rows(["a", "b"]) == (["a", "b"], 0)
    assert all_day_rows(["a", "b", "c", "d"]) == (["a"], 3)


# ----- properties ---------------------------------------------------------------------

quarter_hours = st.integers(min_value=-8, max_value=26 * 4)


@st.composite
def days(draw: st.DrawFn) -> list[Span]:
    count = draw(st.integers(min_value=0, max_value=12))
    out = []
    for i in range(count):
        start = draw(quarter_hours)
        length = draw(st.integers(min_value=1, max_value=16))
        out.append(span(f"e{i}", start / 4, (start + length) / 4))
    return out


@given(days())
@settings(max_examples=200, deadline=None)
def test_no_two_blocks_overlap_and_every_block_is_inside_the_frame(spans: list[Span]) -> None:
    start, end = window(at(8), spans)
    line = Timeline(start, end, top=200, height=800)
    placed = place(spans, line, left=100, width=400)
    for p in placed:
        assert p.x >= 100 and p.x + p.width <= 500 + 1e-6
        assert p.y >= 200 and p.y + p.height <= 1000 + 1e-6
    by_key = {s.key: s for s in spans}
    for i, a in enumerate(placed):
        for b in placed[i + 1 :]:
            sa, sb = by_key[a.key], by_key[b.key]
            if sa.start < sb.end and sb.start < sa.end:  # at the same time: apart
                assert a.x + a.width <= b.x + 1e-6 or b.x + b.width <= a.x + 1e-6


@given(days())
@settings(max_examples=200, deadline=None)
def test_every_event_in_the_day_is_placed(spans: list[Span]) -> None:
    start, end = window(at(8), spans)
    line = Timeline(start, end, top=0, height=800)
    placed = {p.key for p in place(spans, line, 0, 400)}
    in_day = {s.key for s in spans if s.end > at(0) and s.start < at(24)}
    assert in_day <= placed
