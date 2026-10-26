"""Energy-aware chore levels (S4): a chore with (Low)/(Medium)/(High) steps is nudged with
the level that suits the day, in words."""

import re

from tests.scenarios.harness import Scenario
from themi.core.tasks import TaskBoard

BATHROOM = [
    "(Low) Wipe sink/counter",
    "(Low) Clean toilet",
    "(Low) Vacuum floor",
    "(Medium) Mop floor",
    "(High) Clean the shower",
]


def board(scenario: Scenario) -> TaskBoard:
    assert scenario.app.services.taskboard is not None
    return scenario.app.services.taskboard


async def nudge_for(scenario: Scenario, level: str | None) -> str:
    erin = scenario.member("Erin")
    if level is not None:
        value = {"low": -1, "medium": 0, "high": 1}[level]
        scenario.app.services.energy.record(erin, "day_level", value, f"{level} day")
    await board(scenario).create(
        erin, "Clean upstairs bathroom", "physical", 3, steps=BATHROOM, assignee=erin
    )
    # On a low day the nudge may wait for a better moment, so read it from the outbox.
    (row,) = scenario.app.db.query(
        "SELECT text FROM outbox WHERE kind = 'task' AND text LIKE '%upstairs bathroom%'"
    )
    return str(row["text"])


async def test_a_low_day_gets_the_lighter_version(scenario: Scenario) -> None:
    text = await nudge_for(scenario, "low")
    assert "A lighter version for today:" in text
    assert "> - (Low) Wipe sink/counter\n> - (Low) Clean toilet\n> - (Low) Vacuum floor" in text
    assert "Mop" not in text and "shower" not in text
    assert "The rest is there too if you feel like more." in text


async def test_a_medium_day_adds_the_medium_steps(scenario: Scenario) -> None:
    text = await nudge_for(scenario, "medium")
    assert "A middle version for today:" in text
    assert "> - (Medium) Mop floor" in text and "(Low) Clean toilet" in text
    assert "shower" not in text


async def test_a_high_day_gets_everything(scenario: Scenario) -> None:
    text = await nudge_for(scenario, "high")
    assert "The full version for today:" in text and "(High) Clean the shower" in text
    assert "The rest is there too" not in text


async def test_untagged_steps_are_unchanged_and_no_numbers_show(scenario: Scenario) -> None:
    erin = scenario.member("Erin")
    await board(scenario).create(
        erin, "Clean the bird cage", "physical", 2, steps=["Shake tray"], assignee=erin
    )
    await scenario.advance(hours=4, minutes=1)
    (text,) = [t for t in scenario.inbox("Erin") if "bird cage" in t]
    assert "version for today" not in text and "> - Shake tray" in text
    level_text = await nudge_for(scenario, None)  # no stated level: the estimate decides
    assert "version for today:" in level_text
    assert not re.search(r"\d", level_text.replace("4", ""))  # no scores anywhere


async def test_the_model_sees_the_suggested_level(scenario: Scenario) -> None:
    erin = scenario.member("Erin")
    scenario.app.services.energy.record(erin, "day_level", -1, "low day")
    await board(scenario).create(
        erin, "Clean upstairs bathroom", "physical", 3, steps=BATHROOM, assignee=erin
    )
    items = [
        i.summary for i in scenario.app.services.open_items(erin) if i.summary.startswith("Task")
    ]
    assert "Suggested today: the lighter (Low) version." in items[0]
