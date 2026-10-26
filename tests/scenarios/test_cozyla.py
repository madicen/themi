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
