"""PT6a: the sentences Themi says about parcels (wall, morning message, chat)."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from themi_google import parcel_words as words
from themi_google.deliveries import Parcel

LA = ZoneInfo("America/Los_Angeles")
TODAY = date(2026, 10, 21)  # a Wednesday
CHEWY = Parcel(
    id=1,
    member_id=1,
    carrier="ups",
    number="1Z5R89390357567127",
    shop="Chewy",
    status="out_for_delivery",
    expected_day=TODAY,
    window_start="",
    window_end="",
    problem="",
    delivered_at=None,
    left_at="",
    source="email",
    updated_at=datetime(2026, 10, 21, 15, 0, tzinfo=UTC),
)


def test_clock_and_window() -> None:
    assert words.clock("14:15") == "2:15 pm" and words.clock("09:00") == "9 am"
    assert words.clock("00:30") == "12:30 am" and words.clock("12:00") == "12 pm"
    assert words.window(replace(CHEWY, window_start="14:15", window_end="16:15")) == (
        "between 2:15 and 4:15 pm"
    )
    assert words.window(replace(CHEWY, window_start="10:00", window_end="14:00")) == (
        "between 10 am and 2 pm"
    )
    assert words.window(CHEWY) == ""


def test_days() -> None:
    assert words.day_words(TODAY, TODAY) == "today"
    assert words.day_words(date(2026, 10, 22), TODAY) == "tomorrow"
    assert words.day_words(date(2026, 10, 23), TODAY) == "Friday"
    assert words.day_words(date(2026, 11, 3), TODAY) == "on 3 November"


def test_due() -> None:
    assert words.due(CHEWY) == "A delivery from Chewy is due today."
    timed = replace(CHEWY, window_start="14:00", window_end="16:00")
    assert words.due(timed) == "A delivery from Chewy is due between 2 and 4 pm."
    signed = replace(timed, signature=True)
    assert words.due(signed) == (
        "A delivery from Chewy is due today and needs someone to sign for it."
    )


def test_came() -> None:
    delivered = replace(CHEWY, status="delivered")
    assert words.came(delivered, LA) == "A delivery from Chewy came today. It may be at the door."
    looked = replace(
        delivered,
        source="lookup",
        delivered_at=datetime(2026, 10, 21, 20, 40, tzinfo=UTC),
        left_at="Front Door",
    )
    assert words.came(looked, LA) == (
        "A delivery from Chewy came at 1:40 pm. It was left at the front door."
    )


def test_problems() -> None:
    held = replace(CHEWY, status="problem", problem="Held at Post Office", carrier="usps")
    assert (
        words.problem(held, TODAY) == "The delivery from Chewy has a hitch (Held at Post Office)."
    )
    missed = replace(
        CHEWY,
        status="problem",
        problem="The receiver was not available for delivery.",
        expected_day=date(2026, 10, 22),
    )
    assert words.problem(missed, TODAY) == (
        "UPS couldn't deliver the parcel from Chewy. It's now due tomorrow."
    )
    unsettled = replace(missed, carrier="fedex usps")
    assert words.problem(unsettled, TODAY).startswith("The carrier couldn't deliver")


def test_moved_and_why() -> None:
    later = replace(CHEWY, expected_day=date(2026, 10, 23), moved_from=TODAY, source="lookup")
    assert words.moved(later, TODAY) == "The delivery from Chewy is now due Friday."
    assert words.why(later, "so") == "UPS's tracking says so."
    assert words.why(CHEWY, "it's expected today") == "A shipping email says it's expected today."


def test_several() -> None:
    amazon = replace(CHEWY, shop="Amazon")
    assert words.several([amazon, amazon], "are due today.") == (
        "Two deliveries from Amazon are due today."
    )
    assert words.several([amazon, CHEWY], "are due today.") == (
        "Deliveries from Amazon and Chewy are due today."
    )


def test_the_morning_line() -> None:
    timed = replace(CHEWY, window_start="14:00", window_end="16:00")
    assert words.morning([timed], TODAY) == "A delivery today, from Chewy (between 2 and 4 pm)."
    amazon = replace(CHEWY, id=2, shop="Amazon")
    assert words.morning([amazon, timed], TODAY) == (
        "Two deliveries today, from Amazon and Chewy (Chewy between 2 and 4 pm)."
    )
    held = replace(CHEWY, id=3, shop="Etsy", status="problem", problem="Held at Post Office")
    assert (
        words.morning([held], TODAY) == "The delivery from Etsy has a hitch (Held at Post Office)."
    )
    later = replace(CHEWY, expected_day=date(2026, 10, 23))
    delivered = replace(CHEWY, status="delivered")
    assert words.morning([later, delivered], TODAY) is None


def test_chat_describes_each() -> None:
    assert words.describe(replace(CHEWY, expected_day=date(2026, 10, 23)), TODAY, LA) == (
        "The delivery from Chewy is due Friday."
    )
    assert words.describe(replace(CHEWY, expected_day=None), TODAY, LA) == (
        "The delivery from Chewy is on its way; no one has said when it's due."
    )
    came = replace(CHEWY, status="delivered", expected_day=date(2026, 10, 20))
    assert words.describe(came, TODAY, LA) == "The delivery from Chewy came yesterday."


def test_nothing_says_a_tracking_number() -> None:
    samples = [
        words.due(CHEWY),
        words.came(replace(CHEWY, status="delivered"), LA),
        words.problem(replace(CHEWY, status="problem", problem="Delivery attempted"), TODAY),
        words.morning([CHEWY], TODAY) or "",
        words.describe(CHEWY, TODAY, LA),
    ]
    assert all(CHEWY.number not in s for s in samples)
