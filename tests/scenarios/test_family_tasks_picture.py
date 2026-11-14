"""F43b (Michael's idea #208, reply 466): "our tasks" is a picture of everyone's, a column
each with what either can do across the bottom; "chores and tasks" puts each person's chart
chores first; emoji are in it. The clock starts Wednesday 21 October 2026 at 09:00."""

from __future__ import annotations

from datetime import date

from tests.scenarios.harness import Scenario
from tests.scenarios.test_focus import board, task
from tests.scenarios.test_list_pictures import ask, captions
from themi.core import keys
from themi.standard.task_card import SHARED_NAME, task_cards

TUE = date(2026, 10, 20)
WED = date(2026, 10, 21)


def titles(lane) -> list[str]:
    return [c.title for g in lane.groups for c in g.cards]


async def family(scenario: Scenario) -> None:
    await task(scenario, "Husband", "Clean the bird cage", due=TUE)
    await task(scenario, "Husband", "Text Susan", due=None)
    await task(scenario, "Erin", "Call the vet", due=WED)
    await task(scenario, "Erin", "Water the plants", due=None)
    shared = await task(scenario, "Erin", "Vacuum maintenance", due=TUE)
    await board(scenario).make_either(shared.id)


async def test_ones_own_has_its_emoji_in_order(scenario: Scenario) -> None:
    await family(scenario)
    data = task_cards(scenario.app.services, scenario.member("Husband"))
    assert data is not None and data.title == "Husband's tasks"
    (lane,) = data.lanes
    cards = [c for g in lane.groups for c in g.cards]
    assert [(c.title, c.emoji, c.note) for c in cards] == [
        ("Clean the bird cage", "🦜", "was due Tue 20 Oct"),
        ("Vacuum maintenance", "🧹", "was due Tue 20 Oct, shared"),  # either of them's
        ("Text Susan", "", ""),
    ]


async def test_everyone_is_a_column_each_and_shared_across_the_bottom(
    scenario: Scenario,
) -> None:
    await family(scenario)
    data = task_cards(scenario.app.services, scenario.member("Husband"), "everyone")
    assert data is not None and data.title == "Everyone's tasks"
    assert [lane.name for lane in data.lanes] == ["Erin", "Husband"]
    erin, husband = data.lanes
    assert titles(erin) == ["Call the vet", "Water the plants"]
    assert titles(husband) == ["Clean the bird cage", "Text Susan"]
    assert [c.title for c in data.shared] == ["Vacuum maintenance"]


async def test_a_named_persons_tasks(scenario: Scenario) -> None:
    await family(scenario)
    data = task_cards(scenario.app.services, scenario.member("Husband"), "Erin")
    assert data is not None and data.title == "Erin's tasks"
    (lane,) = data.lanes
    assert "Call the vet" in titles(lane) and "Vacuum maintenance" in titles(lane)


async def test_with_chores_the_chart_comes_first_and_nothing_twice(scenario: Scenario) -> None:
    await family(scenario)
    bins = await task(scenario, "Husband", "Bring bins in", due=WED)
    queue = scenario.app.services.get(keys.chart_queue)
    queue.chart_for = lambda member, today: (  # type: ignore[method-assign]
        [board(scenario).get(bins.id)] if member.name == "Husband" else []
    )
    data = task_cards(scenario.app.services, scenario.member("Husband"), "everyone", True)
    assert data is not None and data.title == "Everyone's chores and tasks"
    husband = data.lanes[1]
    assert husband.groups[0].heading == "On the chart"
    assert [c.title for c in husband.groups[0].cards] == ["Bring bins in"]
    assert titles(husband).count("Bring bins in") == 1
    assert husband.groups[0].cards[0].emoji == "🗑️"


async def test_asking_for_our_tasks_sends_the_family_picture(scenario: Scenario) -> None:
    await family(scenario)
    args = {"who": "everyone", "with_chores": False}
    offered = await ask(
        scenario, "Husband", "Can I see a picture of our tasks?", "show_tasks_picture", args
    )
    assert "show_tasks_picture" in offered
    assert captions(scenario, "Husband") == ["Everyone's tasks."]


async def test_chores_and_tasks_together(scenario: Scenario) -> None:
    await family(scenario)
    args = {"who": "everyone", "with_chores": True}
    await ask(
        scenario,
        "Husband",
        "Can I see a picture of the family chores and tasks?",
        "show_tasks_picture",
        args,
    )
    assert captions(scenario, "Husband") == ["Everyone's chores and tasks."]


async def test_without_pictures_its_words_with_emoji(scenario: Scenario) -> None:
    def broken(svg: str, width: int | None) -> bytes:
        raise ValueError("no fonts here")

    scenario.app.services.get(keys.drawings).renderer.convert = broken
    await family(scenario)
    await ask(
        scenario,
        "Husband",
        "Our tasks as a picture",
        "show_tasks_picture",
        {"who": "everyone", "with_chores": False},
    )
    (words,) = [t for t in scenario.inbox("Husband") if t.startswith("Everyone's tasks")]
    assert "- 🦜 Clean the bird cage (was due Tue 20 Oct)" in words
    assert f"{SHARED_NAME}:\n- 🧹 Vacuum maintenance (was due Tue 20 Oct)" in words


async def test_someone_unknown_is_asked_about(scenario: Scenario) -> None:
    await family(scenario)
    await ask(
        scenario,
        "Husband",
        "Show me Bob's tasks",
        "show_tasks_picture",
        {"who": "Bob", "with_chores": False},
    )
    assert scenario.pictures("Husband") == []


async def test_the_chore_chart_alone_is_still_its_own_tool(scenario: Scenario) -> None:
    offered = await ask(scenario, "Husband", "Show the chore chart", "show_chore_chart", {})
    assert "show_chore_chart" in offered
