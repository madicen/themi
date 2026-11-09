"""F37c: a card's date says its year when it's more than a year off (16 Nov 2054 is a
Monday too, so "Mon 16 Nov" looked like next week)."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from themi_google.events import When, describe

PACIFIC = ZoneInfo("America/Los_Angeles")


def all_day(year: int) -> When:
    starts = datetime(year, 11, 16, tzinfo=PACIFIC)
    return When(starts, starts + timedelta(days=1), True)


@pytest.mark.usefixtures("frozen_clock")
def test_the_year_is_said_only_when_its_far_off() -> None:
    assert describe("Resume", all_day(2054), "", PACIFIC) == "Resume, Mon 16 Nov 2054, all day"
    assert describe("Resume", all_day(2026), "", PACIFIC) == "Resume, Mon 16 Nov, all day"
