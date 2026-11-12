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


# ----- F38a (bug #190): events with no title are never twins ----------------------------


def test_two_untitled_events_arent_alike() -> None:
    # Card 1674's pair: both "(no title)" (a work calendar that hides titles), overlapping.
    assert not alike(event("(no title)", 11, 15), event("(no title)", 12, 13))
    assert not alike(event("(no title)"), event("(no title)"))  # the very same times
    assert not alike(event(""), event("  "))


def test_untitled_against_a_title_isnt_a_pair() -> None:
    assert not alike(event("(no title)"), event("Dentist"))
    assert not alike(event("Dentist"), event("(no title)"))


def test_untitled() -> None:
    from themi.core.wording import NO_TITLE, untitled

    assert untitled("") and untitled("   ") and untitled(NO_TITLE) and untitled("(No Title)")
    assert not untitled("Dentist")


def test_untitled_events_at_one_place_have_their_own_heads_up_key() -> None:
    from themi.core.calendar_view import Entry
    from themi_google.travel import TravelHeadsUps as Travel

    def entry(title: str, eid: str) -> Entry:
        at = datetime(2026, 10, 28, 13, tzinfo=UTC)
        return Entry(1, title, "1 Hacker Way", at, at, False, False, None, "primary", eid)

    assert Travel._event_key(entry("(no title)", "a")) != Travel._event_key(
        entry("(no title)", "b")
    )
    assert Travel._event_key(entry("Dentist", "a")) == Travel._event_key(entry("Dentist", "b"))
