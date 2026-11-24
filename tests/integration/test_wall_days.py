"""F59c (Michael's idea #255): the wall keeps each person's day until their rollover (F34j),
as Telegram and the chore chart do, and shows a person with a chart limit (C2d) only the
chores their chart shows. The scenario starts Wednesday 21 October 2026, 9 am, Los Angeles;
the husband's day rolls over at 4 am, Erin's at midnight."""

from __future__ import annotations

from datetime import date, datetime

from tests.integration.test_chore_chart import chore, limit
from tests.integration.test_wall_screen import task, wall
from tests.scenarios.harness import Scenario
from themi import clock
from themi.core import keys
from themi_home.wall_view import WallColumn, WallView

__all__ = ["wall"]  # the fixture

WED, THU = date(2026, 10, 21), date(2026, 10, 22)


def move_to(s: Scenario, day: date, hour: int, minute: int = 0) -> None:
    target = datetime(
        day.year, day.month, day.day, hour, minute, tzinfo=WallView(s.app.services).tz()
    )
    clock.advance(target - clock.now())


def column(s: Scenario, name: str) -> WallColumn:
    member = s.member(name)
    return next(c for c in WallView(s.app.services).columns() if c.member_id == member.id)


def shown(s: Scenario, name: str, section: str) -> list[str]:
    found = next((x for x in column(s, name).sections if x.title == section), None)
    return [i.title for i in found.items if not i.done] if found else []


def late_rollover(s: Scenario) -> None:
    s.app.db.execute("UPDATE members SET day_ends = 4 WHERE id = ?", (s.member("Husband").id,))


async def test_after_midnight_its_still_yesterday_for_someone_whose_day_ends_at_4(
    wall: Scenario,
) -> None:
    late_rollover(wall)
    await task(wall, "Husband", "Take out trash", due=THU, chore=True)
    await task(wall, "Erin", "Water the plants", due=THU, chore=True)
    move_to(wall, THU, 0, 30)
    assert "Take out trash" not in shown(wall, "Husband", "Chores")
    assert "Water the plants" in shown(wall, "Erin", "Chores")
    move_to(wall, THU, 4, 30)
    assert "Take out trash" in shown(wall, "Husband", "Chores")


async def test_what_they_did_that_evening_still_counts_after_midnight(wall: Scenario) -> None:
    late_rollover(wall)
    trash = await task(wall, "Husband", "Take out trash", due=WED, chore=True)
    dishes = await task(wall, "Erin", "Run the dishwasher", due=WED, chore=True)
    board = wall.app.services.get(keys.taskboard)
    move_to(wall, WED, 21)
    await board.complete(trash.id, wall.member("Husband"))
    await board.complete(dishes.id, wall.member("Erin"))
    move_to(wall, THU, 0, 30)
    assert column(wall, "Husband").summary.startswith("1 done")
    assert not column(wall, "Erin").summary.startswith("1 done")  # her day is over


async def test_a_tick_after_midnight_counts_for_their_day(wall: Scenario) -> None:
    late_rollover(wall)
    trash = await task(wall, "Husband", "Take out trash", due=WED, chore=True)
    move_to(wall, THU, 0, 30)
    assert "Take out trash" in shown(wall, "Husband", "Chores")
    await wall.app.services.get(keys.taskboard).complete(trash.id, wall.member("Husband"))
    assert "Take out trash" not in shown(wall, "Husband", "Chores")
    assert column(wall, "Husband").summary.startswith("1 done")


async def test_someone_with_a_chart_limit_sees_only_what_their_chart_shows(
    wall: Scenario,
) -> None:
    if wall.app.services.maybe(keys.chart_queue) is None:
        import pytest

        pytest.skip("no chore chart in this app")
    await chore(wall, "Clean the kitchen", "every Wednesday")
    await chore(wall, "Fold laundry", "every Wednesday")
    await chore(wall, "Dust", "every Wednesday")
    pill = await chore(wall, "Mimi pill", "every day")
    wall.app.db.execute("UPDATE tasks SET importance = 'high' WHERE id = ?", (pill.id,))
    assert len(shown(wall, "Erin", "Chores")) == 4  # no limit: all of them
    limit(wall, "Erin", 1)
    chores = shown(wall, "Erin", "Chores")
    assert "Mimi pill" in chores  # an important one always shows
    assert len(chores) == 2
    limit(wall, "Erin", 0)
    assert len(shown(wall, "Erin", "Chores")) == 4


async def test_the_person_page_keeps_their_day_and_limit_too(wall: Scenario) -> None:
    from themi_home.wall_views import WallViews

    late_rollover(wall)
    await task(wall, "Husband", "Take out trash", due=THU, chore=True)
    move_to(wall, THU, 0, 30)
    view = WallViews(WallView(wall.app.services)).person(wall.member("Husband").id)
    assert view is not None and view.chores is not None
    assert "Take out trash" not in [i.title for i in view.chores.items]
