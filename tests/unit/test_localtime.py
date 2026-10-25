from datetime import datetime
from zoneinfo import ZoneInfo

from tests.fixtures.family import SeededFamily
from themi.accounts import SYSTEM
from themi.localtime import in_quiet_hours, next_waking_start, quiet_hours_end, start_of_local_day

TZ = "America/Los_Angeles"
PACIFIC = ZoneInfo(TZ)


def at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=PACIFIC)


def test_overnight_quiet_hours(family: SeededFamily) -> None:
    erin = family.erin  # 21:30-08:00
    assert not in_quiet_hours(erin, at(21, 21, 29), TZ)
    assert in_quiet_hours(erin, at(21, 21, 30), TZ)
    assert in_quiet_hours(erin, at(22, 3), TZ)
    assert not in_quiet_hours(erin, at(22, 8), TZ)


def test_daytime_quiet_hours_and_none(family: SeededFamily) -> None:
    nap = family.store.update_settings(
        SYSTEM, family.erin.id, quiet_start="13:00", quiet_end="15:00"
    )
    assert in_quiet_hours(nap, at(21, 14), TZ)
    assert not in_quiet_hours(nap, at(21, 15), TZ)
    none = family.store.update_settings(
        SYSTEM, family.erin.id, quiet_start="00:00", quiet_end="00:00"
    )
    assert not in_quiet_hours(none, at(21, 3), TZ)


def test_quiet_hours_end(family: SeededFamily) -> None:
    erin = family.erin
    assert quiet_hours_end(erin, at(21, 23), TZ) == at(22, 8)
    assert quiet_hours_end(erin, at(22, 2), TZ) == at(22, 8)
    assert quiet_hours_end(erin, at(21, 12), TZ) == at(21, 12)


def test_next_waking_start(family: SeededFamily) -> None:
    erin = family.erin
    assert next_waking_start(erin, at(21, 12), TZ) == at(22, 8)
    assert next_waking_start(erin, at(21, 7), TZ) == at(21, 8)


def test_start_of_local_day_is_pacific_midnight() -> None:
    utc_morning = datetime(2026, 10, 22, 3, 0, tzinfo=ZoneInfo("UTC"))  # 20:00 Pacific on the 21st
    assert start_of_local_day(utc_morning, TZ) == at(21, 0)
