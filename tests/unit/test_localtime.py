from datetime import datetime, time
from zoneinfo import ZoneInfo

from tests.fixtures.family import SeededFamily
from themi.accounts import SYSTEM, BusyTime
from themi.localtime import (
    free_from,
    in_busy_time,
    in_quiet_hours,
    next_waking_start,
    quiet_hours_end,
    start_of_local_day,
)

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


WORKDAYS = BusyTime((0, 1, 2, 3, 4), time(9), time(17))


def test_free_from_skips_busy_times(family: SeededFamily) -> None:
    erin = family.store.update_settings(SYSTEM, family.erin.id, busy_times=[WORKDAYS])
    assert in_busy_time(erin, at(21, 10), TZ)  # Wednesday 10:00
    assert free_from(erin, at(21, 10), TZ) == at(21, 17)
    assert free_from(erin, at(21, 17), TZ) == at(21, 17)  # the end is free
    assert free_from(erin, at(24, 10), TZ) == at(24, 10)  # Saturday isn't busy
    assert not in_busy_time(erin, at(25, 12), TZ)


def test_free_from_chains_quiet_hours_and_busy_times(family: SeededFamily) -> None:
    early = BusyTime((0, 1, 2, 3, 4), time(8), time(9, 30))
    erin = family.store.update_settings(SYSTEM, family.erin.id, busy_times=[early])
    # Quiet until 08:00 Thursday, then busy until 09:30.
    assert free_from(erin, at(21, 23), TZ) == at(22, 9, 30)
    late = BusyTime((2,), time(20), time(21, 30))  # Wednesdays, right up to quiet hours
    erin = family.store.update_settings(SYSTEM, family.erin.id, busy_times=[late])
    assert free_from(erin, at(21, 20, 15), TZ) == at(22, 8)


def test_busy_time_labels() -> None:
    assert WORKDAYS.label() == "Mon-Fri 09:00-17:00"
    assert BusyTime((5, 6), time(10), time(12)).label() == "Sat, Sun 10:00-12:00"
    assert BusyTime((0, 2, 4), time(18), time(19, 30)).label() == "Mon, Wed, Fri 18:00-19:30"
