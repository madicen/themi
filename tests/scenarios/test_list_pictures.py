"""F42g (Michael's bug #206, reply 448): tasks, routines and the day as pictures, each its
own. "And tasks as a picture" sent the chore chart again. The clock starts on Wednesday 21
October 2026 at 09:00, Pacific time."""

from __future__ import annotations

from datetime import date

from tests.scenarios.harness import Scenario
from tests.scenarios.test_focus import task
from tests.scenarios.test_routines import add, routines
from themi.core import keys
from themi.standard.list_card import routines_data, tasks_data

TUE = date(2026, 10, 20)
WED = date(2026, 10, 21)


async def ask(scenario: Scenario, name: str, said: str, tool: str, args: dict) -> set[str]:
    """Say it, with the model faked to call `tool`; the tools this turn's first call had."""
    before = len(scenario.primary.requests)
    scenario.primary.queue_tool_call(tool, args)
    scenario.primary.queue_text("Here.")
    await scenario.say(name, said)
    return {t.name for t in scenario.primary.requests[before].tools}


def captions(scenario: Scenario, name: str) -> list[str]:
    return [p.get("caption", "") for p in scenario.pictures(name)]


async def test_tasks_overdue_first_then_today_then_any_time(scenario: Scenario) -> None:
    await task(scenario, "Erin", "Water the plants", due=None)
    await task(scenario, "Erin", "Call the vet", due=WED)
    await task(scenario, "Erin", "Return the books", due=TUE)
    data = tasks_data(scenario.app.services, scenario.member("Erin"))
    assert data is not None
    assert [(s.heading, [(r.text, r.note) for r in s.rows]) for s in data.sections] == [
        ("Overdue", [("Return the books", "was due Tue 20 Oct")]),
        ("Today", [("Call the vet", "")]),
        ("Any time", [("Water the plants", "")]),
    ]


async def test_asking_for_tasks_as_a_picture_sends_that(scenario: Scenario) -> None:
    await task(scenario, "Erin", "Call the vet", due=WED)
    offered = await ask(scenario, "Erin", "Show me my tasks as a picture", "show_tasks_picture", {})
    assert "show_tasks_picture" in offered
    assert captions(scenario, "Erin") == ["Your tasks."]


async def test_routines_with_ticks_and_tomorrows(scenario: Scenario) -> None:
    add(scenario, "Erin", "Evening", "Cycle dishwasher")
    add(scenario, "Erin", "Evening", "Take meds")
    add(scenario, "Erin", "Evening", "Cover the birdcage")
    erin = scenario.member("Erin")
    r = routines(scenario)
    evening = r.find(erin, "Evening")
    assert evening is not None
    first, second, _ = r.items(evening)
    r.tick(first, WED)
    r.tick(second, WED)
    data = routines_data(scenario.app.services, erin)
    assert data is not None
    (section,) = data.sections
    assert [r.done for r in section.rows] == [True, True, False]
    tomorrow = routines_data(scenario.app.services, erin, date(2026, 10, 22))
    assert tomorrow is not None
    assert [r.done for r in tomorrow.sections[0].rows] == [False, False, False]

    said = "A picture of my routines please"
    offered = await ask(scenario, "Erin", said, "show_routines_picture", {"day": "today"})
    assert "show_routines_picture" in offered
    assert captions(scenario, "Erin") == ["Your routines."]


async def test_without_pictures_its_words(scenario: Scenario) -> None:
    def broken(svg: str, width: int | None) -> bytes:
        raise ValueError("no fonts here")

    scenario.app.services.get(keys.drawings).renderer.convert = broken
    await task(scenario, "Erin", "Call the vet", due=WED)
    await ask(scenario, "Erin", "My tasks as a picture", "show_tasks_picture", {})
    assert any(t.startswith("Erin's tasks, Wed 21 Oct:") for t in scenario.inbox("Erin"))
    assert scenario.pictures("Erin") == []


async def test_a_picture_of_my_day_is_the_day_card(scenario: Scenario) -> None:
    offered = await ask(scenario, "Erin", "Let's see the morning picture", "show_day", {})
    assert "show_day" in offered
    assert captions(scenario, "Erin") == ["Your day."]


async def test_tasks_then_routines_after_the_chores_are_their_own_pictures(
    scenario: Scenario,
) -> None:
    await task(scenario, "Husband", "Bring bins in", due=WED)
    add(scenario, "Husband", "Evening", "Take meds")
    for tool, said in [
        ("show_tasks_picture", "And tasks as a picture"),
        ("show_routines_picture", "And my routines as a picture"),
    ]:
        args = {"day": "today"} if "routines" in tool else {}
        assert tool in await ask(scenario, "Husband", said, tool, args), (tool, said)
    assert captions(scenario, "Husband") == ["Your tasks.", "Your routines."]
