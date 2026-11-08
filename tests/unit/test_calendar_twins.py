"""F34e: which two events could be one thing."""

from __future__ import annotations

from datetime import UTC, datetime

from themi_google.calendar_twins import alike, appointment_like, overlap
from themi_google.events import Found, When


def event(title: str, start: int = 13, end: int = 14) -> Found:
    when = When(datetime(2026, 10, 28, start, tzinfo=UTC), datetime(2026, 10, 28, end, tzinfo=UTC),
                False)  # fmt: skip
    return Found(1, "primary", title, title, "", when, None)


def test_a_placeholder_and_the_clinics_event_are_alike() -> None:
    assert appointment_like("ND psych in person")
    assert appointment_like("Return Patient Visit with Thuc Quyen Nguyen, MD")
    assert alike(event("ND psych in person"), event("Return Patient Visit with Dr Nguyen"))
    assert alike(event("Dentist"), event("Dentist cleaning"))


def test_unrelated_events_arent() -> None:
    assert not alike(event("Lunch with Sam"), event("Call mom"))
    assert not appointment_like("Do the taxes")
    assert not alike(event("Soccer practice"), event("Dentist"))


def test_overlap() -> None:
    assert overlap(event("a", 13, 14).when, event("b", 13, 15).when)
    assert not overlap(event("a", 13, 14).when, event("b", 14, 15).when)
