"""C1b: the Cozyla wall calendar's to-do list and Themi's tasks, as the family sees them."""

from __future__ import annotations

from tests.fakes.cozyla import FakeCozyla
from tests.scenarios.harness import Scenario


async def test_ticking_a_to_do_off_on_the_wall_stops_the_nudges(
    scenario: Scenario, fake_cozyla: FakeCozyla
) -> None:
    board = scenario.app.services.taskboard
    assert board is not None
    erin = scenario.member("Erin")
    vet = await board.create(erin, "Call the vet", "call", 2, assignee=erin)
    assert any("Call the vet" in t for t in scenario.inbox("Erin"))
    await scenario.tap("Erin", "Later")  # it'll come back around in a few hours

    await scenario.run_periodic("cozyla.sync")
    (todo,) = fake_cozyla.in_list(scenario.cozyla_list)
    assert (todo["todoTitle"], todo["assignMemberUid"]) == ("Call the vet", "m-erin")

    fake_cozyla.tick(todo["todoId"])  # Erin did it, and ticked it off on the wall
    await scenario.run_periodic("cozyla.sync")
    nudges = len([t for t in scenario.inbox("Erin") if "Call the vet" in t])
    await scenario.advance(hours=6)
    await scenario.run_periodic("tasks.resurface")
    await scenario.advance(minutes=1)
    assert board.get(vet.id).status == "done"
    assert len([t for t in scenario.inbox("Erin") if "Call the vet" in t]) == nudges


async def test_a_chore_ticked_on_the_chart_isnt_asked_about(
    scenario: Scenario, fake_cozyla: FakeCozyla
) -> None:
    """C2b: Erin cleans the kitchen at lunch and ticks it on the wall's chore chart; Themi
    doesn't ask about it that evening."""
    from datetime import date

    from themi.core.repeat import parse

    board = scenario.app.services.taskboard
    assert board is not None
    erin = scenario.member("Erin")
    kitchen = await board.create(erin, "Clean the kitchen", "physical", 2, assignee=erin)
    await board.set_schedule(
        kitchen.id, erin, repeat=parse("every Wednesday at 6pm", scenario.today())
    )
    await scenario.run_periodic("cozyla.chores")
    before = len(scenario.inbox("Erin"))

    await scenario.advance(hours=3)  # noon
    uid = fake_cozyla.chore_named("Clean the kitchen")["choreUid"]
    fake_cozyla.tick_chore(uid, "m-erin", date(2026, 10, 21))
    await scenario.run_periodic("cozyla.chores")
    await scenario.advance(hours=6, minutes=1)  # 18:01
    assert not any("kitchen" in t for t in scenario.inbox("Erin")[before:])
    assert board.get(kitchen.id).due_on == date(2026, 10, 28)
