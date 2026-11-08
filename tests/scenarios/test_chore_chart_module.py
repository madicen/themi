"""CR21a: the chore chart is its own household module, with no display needed. The wall
only shows it."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import httpx
import pytest

from tests.fakes.cozyla import FakeCozyla
from tests.fakes.telegram_api import FakeTelegram
from tests.fakes.wiring import connector_options
from tests.fixtures.family import SeededFamily
from tests.fixtures.web import sign_in
from tests.scenarios.harness import Scenario
from themi import clock
from themi.app import family_modules
from themi.core import keys
from themi.modules import ModuleError
from themi.standard.tasks import TaskBoard
from themi.storage import migrations
from themi.storage.db import Database
from themi_home.chore_chart import ChartPreferences, ChartQueue, ChoreChartModule

WED = date(2026, 10, 21)  # the scenario clock's first day


async def test_the_chart_works_with_no_wall(scenario: Scenario, site: httpx.AsyncClient) -> None:
    assert "cozyla_chores" not in {m.name for m in scenario.app.modules}
    erin = scenario.member("Erin")
    board: TaskBoard = scenario.app.services.get(TaskBoard)
    chart: ChartQueue = scenario.app.services.get(keys.chart_queue)
    scenario.app.store.save_preferences(erin, erin.id, ChartPreferences, chart_limit=1)
    first = await board.create(erin, "Water the plants", "physical", 1, WED, assignee=erin)
    second = await board.create(erin, "Sort the recycling", "physical", 1, WED, assignee=erin)
    for task in (first, second):
        await chart.put_on(task.id, erin)
    assert chart.has(first.id) and chart.on_chart(board.get(second.id))
    up = chart.up_for(erin)
    assert len(up) == 1  # her limit
    waiting = second if up[0].id == first.id else first
    assert chart.held(board.get(waiting.id), erin)  # its nudge waits its turn
    await sign_in(scenario, site, "Erin")
    home = (await site.get("/")).text
    assert "Chore chart" in home and up[0].title in home
    await chart.put_on(waiting.id, erin, on=False)  # back to the to-do list
    assert not chart.has(waiting.id)


def test_a_family_without_the_chart_has_no_chart_tools(
    family: SeededFamily, fake_telegram: FakeTelegram
) -> None:
    modules = [m for m in family_modules() if m.name != "chore_chart"]
    scenario = Scenario(family, fake_telegram, modules=modules)
    tools = {spec.name for spec in scenario.app.services.tools.specs()}
    assert not tools & {"change_chore_chart", "set_chore_chart_limit", "put_task_on_chore_chart"}
    assert scenario.app.services.maybe(keys.chart_queue) is None


def test_the_wall_needs_the_chart(
    family: SeededFamily, fake_telegram: FakeTelegram, fake_cozyla: FakeCozyla
) -> None:
    every = family_modules(**connector_options(cozyla=fake_cozyla))
    assert "cozyla_chores" in {m.name for m in every}
    with pytest.raises(ModuleError, match="chore_chart"):
        Scenario(
            family,
            fake_telegram,
            cozyla=fake_cozyla,
            modules=[m for m in every if m.name != "chore_chart"],
        )


def test_the_chart_track_copies_what_was_on_the_chart(tmp_path: Path) -> None:
    db = Database(tmp_path / "old.db")
    migrations.apply(db, [m for m in migrations.discover() if m.version < 151])
    now = clock.now().isoformat()
    db.execute(
        "INSERT INTO members (id, name, role, created_at, updated_at) "
        "VALUES (1, 'Erin', 'admin', ?, ?)",
        (now, now),
    )
    for task_id, on_chart, off_wall in ((1, 1, 0), (2, 0, 1)):
        db.execute(
            "INSERT INTO tasks (id, title, kind, effort, assign_reason, created_at, on_chart, "
            "off_wall) VALUES (?, ?, 'physical', 1, '', ?, ?, ?)",
            (task_id, f"Task {task_id}", now, on_chart, off_wall),
        )
    migrations.apply(db)
    assert db.scalar("SELECT off_displays FROM tasks WHERE id = 2") == 1  # renamed, kept
    migrations.apply_track(db, "chore_chart", ChoreChartModule.migrations)  # type: ignore[arg-type]
    assert [r["task_id"] for r in db.query("SELECT task_id FROM chart_tasks")] == [1]
