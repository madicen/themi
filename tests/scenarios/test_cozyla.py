"""C1b: the Cozyla wall calendar's to-do list and Themi's tasks, as the family sees them."""

from __future__ import annotations

import pytest

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
    later = [t for t in scenario.inbox("Erin")[before:] if not t.startswith("Ticked off")]
    assert not any("kitchen" in t for t in later)
    assert board.get(kitchen.id).due_on == date(2026, 10, 28)


async def test_erin_sees_one_chore_at_a_time(scenario: Scenario, fake_cozyla: FakeCozyla) -> None:
    """C2d (ideas #16 and #17): a long chore chart is overwhelming, so Erin sees one chore
    at a time. She ticks it on the wall and the next comes up, with its nudge; the one still
    waiting isn't in her evening list."""
    from datetime import date

    from themi.core.repeat import parse

    board = scenario.app.services.taskboard
    assert board is not None
    erin = scenario.member("Erin")
    scenario.app.store.update_settings(erin, erin.id, chart_limit=1)
    titles = ("Clean the kitchen", "Clean upstairs", "Clean the bathroom")
    for title in titles:
        task = await board.create(erin, title, "physical", 2, assignee=erin)
        await board.set_schedule(task.id, erin, repeat=parse("every Wednesday", scenario.today()))
    await scenario.run_periodic("cozyla.chores")
    assert [c["choreName"] for c in fake_cozyla.chores.values()] == ["Clean the kitchen"]
    assert not any("upstairs" in t or "bathroom" in t for t in scenario.inbox("Erin"))

    await scenario.advance(hours=3)  # noon: the kitchen's done, ticked on the wall
    uid = fake_cozyla.chore_named("Clean the kitchen")["choreUid"]
    fake_cozyla.tick_chore(uid, "m-erin", date(2026, 10, 21))
    await scenario.run_periodic("cozyla.chores")
    await scenario.advance(minutes=1)
    assert "Clean upstairs" in [c["choreName"] for c in fake_cozyla.chores.values()]
    assert any("Clean upstairs" in t for t in scenario.inbox("Erin"))

    quiet = scenario.member("Erin").quiet_start
    await scenario.advance(hours=quiet.hour - 12 - 2, minutes=quiet.minute + 1)
    await scenario.run_periodic("tasks.day_end")
    await scenario.advance(minutes=1)
    (evening,) = [t for t in scenario.inbox("Erin") if t.startswith("Still open today")]
    assert "Clean upstairs" in evening and "bathroom" not in evening


async def test_a_check_in_stays_in_themi(scenario: Scenario, fake_cozyla: FakeCozyla) -> None:
    """Bug #41: an extra "drink some water" check-in, just for today, went onto the wall's
    to-do list. Check-ins are Themi's to ask; jobs still go up."""
    from datetime import date, time

    board = scenario.app.services.taskboard
    assert board is not None
    erin = scenario.member("Erin")
    await board.create(
        erin, "Drink a glass of water", "text", 1, date(2026, 10, 21), assignee=erin,
        check_in=True, due_time=time(14, 30),
    )  # fmt: skip
    await board.create(erin, "Call the vet", "call", 2, assignee=erin)
    await scenario.run_periodic("cozyla.sync")
    assert [t["todoTitle"] for t in fake_cozyla.in_list(scenario.cozyla_list)] == ["Call the vet"]


def _praised(text: str, titles: str) -> bool:
    from themi.core.tasks import PRAISE

    return any(text == f"Ticked off on the wall: {titles}. {word}" for word in PRAISE)


async def test_ticks_on_the_wall_get_a_warm_word_together(
    scenario: Scenario, fake_cozyla: FakeCozyla
) -> None:
    """F19b, the family's answer: "Ticks on the wall should get a nice work message"."""
    board = scenario.app.services.taskboard
    assert board is not None
    erin = scenario.member("Erin")
    for title in ("Call the vet", "Book the dentist"):
        await board.create(erin, title, "call", 2, assignee=erin, nudge=False)
    await scenario.run_periodic("cozyla.sync")
    for todo in fake_cozyla.in_list(scenario.cozyla_list):
        fake_cozyla.tick(todo["todoId"])
    await scenario.run_periodic("cozyla.sync")
    assert not any(t.startswith("Ticked off") for t in scenario.inbox("Erin"))  # a moment
    await scenario.advance(minutes=2)
    ticked = [t for t in scenario.inbox("Erin") if t.startswith("Ticked off")]
    assert len(ticked) == 1
    assert _praised(ticked[0], "Call the vet and Book the dentist")


@pytest.mark.parametrize("case", ["off", "either of them"])
async def test_no_warm_word_when_its_off_or_whose_tick_is_unknown(
    scenario: Scenario, fake_cozyla: FakeCozyla, case: str
) -> None:
    board = scenario.app.services.taskboard
    assert board is not None
    erin = scenario.member("Erin")
    task = await board.create(erin, "Bring bins in", "errand", 1, assignee=erin, nudge=False)
    if case == "off":
        scenario.app.store.update_settings(erin, erin.id, done_praise=False)
    else:
        await board.make_either(task.id)  # either of them could have ticked it
    await scenario.run_periodic("cozyla.sync")
    for todo in fake_cozyla.in_list(scenario.cozyla_list):
        fake_cozyla.tick(todo["todoId"])
    await scenario.run_periodic("cozyla.sync")
    await scenario.advance(minutes=2)
    assert board.get(task.id).status == "done"
    for name in ("Erin", "Husband"):
        assert not any(t.startswith("Ticked off") for t in scenario.inbox(name))
