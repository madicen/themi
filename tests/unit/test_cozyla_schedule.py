"""C2a: Themi's chore schedules and the wall's chore chart, both ways."""

from datetime import date, time

import pytest

from themi.connectors.cozyla.chores import WallSchedule, chore_from, schedule_fields
from themi.connectors.cozyla.schedule import from_wall, to_wall, wall_can_say
from themi.core.repeat import parse, read_back

WED = date(2026, 10, 21)


@pytest.mark.parametrize(
    ("phrase", "every", "count", "days"),
    [
        ("every 2 days", "Daily", 2, ""),
        ("every other Friday", "Weekly", 2, "Friday"),
        ("every Sat and Tue at 6pm", "Weekly", 1, "Tuesday,Saturday"),
        ("the 19th of every month", "Monthly", 1, "19"),
    ],
)
def test_schedules_the_wall_can_say_go_both_ways(
    phrase: str, every: str, count: int, days: str
) -> None:
    rep = parse(phrase, WED)
    wall = to_wall(rep, WED)
    assert (wall.repeats, wall.every, wall.count, wall.days) == (True, every, count, days)
    assert wall.start == WED and wall.forever
    assert from_wall(wall, WED) == rep


def test_an_end_date_and_a_time_go_across() -> None:
    rep = parse("every 2 days at 8am until 30 Oct", WED)
    wall = to_wall(rep, WED)
    assert (wall.forever, wall.end, wall.due_time) == (False, date(2026, 10, 30), time(8))
    assert schedule_fields(wall)["dueTime"] == "08:00"
    back = from_wall(wall, WED)
    assert back is not None and read_back(back) == "Every other day at 8 am, until Fri 30 Oct"


@pytest.mark.parametrize("phrase", ["twice a week", "the first Monday of the month"])
def test_what_the_wall_cant_say_goes_one_round_at_a_time(phrase: str) -> None:
    rep = parse(phrase, WED)
    assert not wall_can_say(rep)
    wall = to_wall(rep, date(2026, 10, 24))
    assert (wall.repeats, wall.start, wall.end) == (False, date(2026, 10, 24), date(2026, 10, 24))
    assert from_wall(wall, WED) is None  # a one-off isn't a schedule


def test_the_familys_chores_read_as_themi_schedules() -> None:
    """As the live API sent them on 2026-10-26."""
    bird = chore_from(
        {
            "choreUid": "a" * 32,
            "choreName": "Clean bird cage",
            "memberRefs": [{"memberUid": "m-michael"}, {"memberUid": "m-erin"}],
            "choreType": "AnyOne",
            "repeats": True,
            "repeatsEvery": "Weekly",
            "repeatsEveryCounts": 1,
            "repeatsIn": "Tuesday,Saturday",
            "startDay": "2026-07-10",
            "endDay": "2026-07-12",
            "dueTime": "23:59",
            "repeatsUntil": True,
        }
    )
    assert bird.members == ("m-michael", "m-erin") and bird.kind == "AnyOne"
    assert bird.schedule.due_time is None and bird.active_on(WED)  # forever, despite endDay
    bird_rep = from_wall(bird.schedule, WED)
    assert bird_rep is not None and read_back(bird_rep) == "Every Tuesday and Saturday"
    pill = chore_from(
        {
            **bird.raw,
            "choreName": "Mimi pill",
            "repeatsEvery": "Daily",
            "repeatsEveryCounts": 2,
            "repeatsIn": "",
            "startDay": "2026-10-02",
            "endDay": "2026-10-30",
            "repeatsUntil": False,
        }
    )
    assert pill.active_on(WED) and not pill.active_on(date(2026, 10, 31))
    pill_rep = from_wall(pill.schedule, WED)
    assert pill_rep is not None and pill_rep.until == date(2026, 10, 30)
    assert from_wall(WallSchedule(True, "Weekly", days=""), WED) is None
