"""F37b (bug #187): when an email's booking is an event already on the calendar."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from themi_google.events import Found, When, same_booking, same_place

PACIFIC = ZoneInfo("America/Los_Angeles")


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, 9, hour, minute, tzinfo=PACIFIC)


def event(title: str, start: datetime, end: datetime, location: str = "") -> Found:
    return Found(1, "primary", "e1", title, location, When(start, end, False), None)


VISIT = When(at(12), at(13), False)


def test_places() -> None:
    assert same_place("1 Hacker Way", "1 Hacker Way, Building 16, Menlo park")
    assert same_place("12 Main Street", "12 main st.")
    assert not same_place("1 Hacker Way", "2 Hacker Way")
    assert not same_place("1", "12 Main St")
    assert not same_place("Online", "Online")  # one word, no number: says too little
    assert not same_place("", "1 Hacker Way")


def test_the_meta_visit() -> None:
    there = event("Samuel | Craig, Gina, and 2 more people", at(12), at(14, 30), "1 Hacker Way")
    assert same_booking("Meta visit with Samuel Carrijo", "1 Hacker Way", VISIT, there, PACIFIC)
    assert same_booking("Meta visit with Samuel Carrijo", "", VISIT, there, PACIFIC)  # a name


def test_only_overlapping_is_two_events() -> None:
    lunch = event("Lunch with the team", at(12, 30), at(13, 30), "Cafe")
    assert not same_booking("Dentist", "Smile Dental", VISIT, lunch, PACIFIC)
    plain = event("Reservation confirmed", at(12), at(14))  # plain words aren't names
    assert not same_booking("Booking: dinner reservation", "", VISIT, plain, PACIFIC)


def test_the_same_times_or_the_same_title_that_day() -> None:
    assert same_booking("Piano", "", VISIT, event("Lesson", at(12), at(13)), PACIFIC)
    assert same_booking("Dentist", "", VISIT, event("Dentist", at(15), at(16)), PACIFIC)
