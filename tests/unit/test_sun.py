"""F9b: sunset, worked out offline from the home's coordinates."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from themi.core.sun import sunset

LA = ZoneInfo("America/Los_Angeles")
SF = (37.7749, -122.4194)


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        (date(2026, 10, 27), datetime(2026, 10, 27, 18, 17, tzinfo=LA)),  # ~6:17 pm PDT (NOAA too)
        (date(2026, 12, 21), datetime(2026, 12, 21, 16, 55, tzinfo=LA)),  # ~4:55 pm PST
        (date(2026, 6, 21), datetime(2026, 6, 21, 20, 35, tzinfo=LA)),  # ~8:35 pm PDT
    ],
)
def test_sunset_in_san_francisco(day: date, expected: datetime) -> None:
    found = sunset(day, *SF, LA)
    assert found is not None
    assert abs(found - expected) <= timedelta(minutes=4), found
    assert found.tzinfo is not None


def test_no_sunset_in_the_arctic_summer() -> None:
    assert sunset(date(2026, 6, 21), 78.2, 15.6, ZoneInfo("Europe/Oslo")) is None
