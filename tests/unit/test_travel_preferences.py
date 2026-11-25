"""F62b: the "be early for" lines a member keeps."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from themi_google.travel import TravelPreferences, early_entries


def test_lines_are_kept_tidy_and_a_later_one_replaces_an_earlier() -> None:
    prefs = TravelPreferences(be_early_for=("Tutoring : 30", "dentist 15 min", "tutoring: 20"))
    assert prefs.be_early_for == ("tutoring: 20", "dentist: 15")
    assert early_entries(prefs.be_early_for) == [("tutoring", 20), ("dentist", 15)]


def test_zero_takes_a_line_away() -> None:
    prefs = TravelPreferences(be_early_for=("tutoring: 30", "Tutoring: 0"))
    assert prefs.be_early_for == ()


@pytest.mark.parametrize("line", ["tutoring", "tutoring: 200"])
def test_a_line_without_minutes_or_too_many_is_refused(line: str) -> None:
    with pytest.raises(ValidationError):
        TravelPreferences(be_early_for=(line,))
