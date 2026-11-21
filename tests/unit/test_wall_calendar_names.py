"""F55f: how the wall's week ahead names a calendar, from the names the Pi has."""

from __future__ import annotations

from themi_home.wall_calendars import label


def test_a_primary_calendar_or_one_named_by_their_address_is_them() -> None:
    assert label("Erin", "primary", "erin@example.com") == "Erin"
    assert label("Erin", "erin@example.com", "erin@example.com") == "Erin"
    assert label("Erin", "", "erin@example.com") == "Erin"


def test_one_named_by_another_address_is_theirs_by_its_domain() -> None:
    assert label("Michael", "michael@stackadapt.com", "michael@gmail.com") == (
        "Michael's Stackadapt"
    )


def test_a_name_that_says_whose_stays_and_another_is_theirs() -> None:
    assert label("Michael", "Michael (Personal)", "michael@gmail.com") == "Michael (Personal)"
    assert label("Erin", "Work", "erin@example.com") == "Erin's Work"
