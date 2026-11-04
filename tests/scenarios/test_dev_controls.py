"""D5b: what someone sees after using `make dev`'s control panel. The panel drives the
same fakes as `make dev`, wired into the scenario harness (scripted models, the clock frozen
on Wednesday 21 October 2026, 9 am)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

from tests.fakes.telegram_api import FakeTelegram
from tests.fixtures.family import SeededFamily
from tests.integration.test_cozyla_chores import board, chore
from tests.scenarios.harness import START, Scenario
from tests.scenarios.test_triage import verdict
from themi import clock
from themi.core.laundry import WASHED_TEXT
from themi.core.tasks import clock_words
from tools.dev.controls import ControlPanel
from tools.dev.fakes import DevFakes

SITE = "http://themi.test"


@dataclass
class Driven:
    scenario: Scenario
    panel: ControlPanel

    async def act(self, section: str, action: str, **values: Any) -> str:
        """As the page does: from another thread, while Themi's loop (this one) runs."""
        return await asyncio.to_thread(self.panel.act, section, action, values)


@pytest.fixture
async def driven(
    family: SeededFamily, fake_telegram: FakeTelegram, tmp_path: Path
) -> AsyncIterator[Driven]:
    fakes = DevFakes(tmp_path / "fakes.json")
    fakes.start([SITE])
    scenario = Scenario(
        family,
        fake_telegram,
        fakes.google,
        fakes.gmail,
        fakes.ourgroceries,
        fakes.gcal,
        fakes.cozyla,
        fakes.travel,
        home_connect=fakes.home_connect,
        thinq=fakes.thinq,
        roborock=fakes.roborock,
        gtasks=fakes.gtasks,
        keep=fakes.keep,
    )
    await scenario.start()
    await fakes.bind(scenario.app, SITE)
    for first in ("devices.thinq", "devices.thinq_push"):  # as the scheduler does on start
        await scenario.run_periodic(first)
    yield Driven(scenario, ControlPanel(fakes))
    await scenario.stop()
    fakes.stop()


async def test_the_washer_finishing_brings_a_nudge_half_an_hour_on(driven: Driven) -> None:
    await driven.act("laundry", "state", machine="Washer", state="Running")
    clock.advance(timedelta(minutes=50))
    await driven.act("laundry", "state", machine="Washer", state="Finished")
    at = clock_words(clock.now().astimezone(START.tzinfo))
    assert await driven.scenario.advance(minutes=29) == []
    assert await driven.scenario.advance(minutes=1) == [WASHED_TEXT.format(at=at)]


async def test_an_email_from_the_panel_is_triaged(driven: Driven) -> None:
    scenario = driven.scenario
    scenario.primary.queue_structured(
        {"results": [verdict(1, "urgent", "Appointment moved to 8 am", urgent_kind="other")]}
    )
    await driven.act("email", "preset", person="Erin", preset="Urgent: an appointment moved")
    (row,) = scenario.app.db.query("SELECT subject, category FROM emails")
    assert (row["subject"], row["category"]) == (
        "Your appointment tomorrow has moved to 8:00 am",
        "urgent",
    )


async def test_a_chore_ticked_on_the_wall_closes_its_round(driven: Driven) -> None:
    scenario = driven.scenario
    kitchen = await chore(scenario, "Clean the kitchen", "every Wednesday")
    await scenario.run_periodic("cozyla.chores")  # onto the chore chart
    await driven.act("wall", "chore", chore="clean the kitchen", person="Erin")
    assert board(scenario).get(kitchen.id).due_on == date(2026, 10, 28)  # done for this week
    runs = scenario.app.db.query("SELECT done_by FROM task_runs WHERE task_id = ?", (kitchen.id,))
    assert [r["done_by"] for r in runs] == [scenario.member("Erin").id]
