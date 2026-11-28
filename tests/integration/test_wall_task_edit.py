"""F65k (Michael's idea #276, "be able to edit tasks and edit due dates on the wall frame"):
a tap on a task's words on a person's page or the Together page unfolds it: its words, day
chips and time, saved through the wall's taps, with an Undo. The scenario's day is
Wednesday 21 October 2026, 9 am, Los Angeles."""

from __future__ import annotations

from datetime import date, time

from tests.integration.test_wall_list_views import post
from tests.integration.test_wall_screen import task, wall
from tests.integration.test_wall_views import get
from tests.scenarios.harness import Scenario
from themi.core import keys

__all__ = ["wall"]  # the fixture

WED, THU = date(2026, 10, 21), date(2026, 10, 22)


def person_url(s: Scenario) -> str:
    return f"/wall/view/person/{s.member('Erin').id}"


async def test_the_words_unfold_the_editor_with_its_day(wall: Scenario) -> None:
    vet = await task(wall, "Erin", "Call the vet", due=WED)
    shown = (await get(wall, f"{person_url(wall)}?edit={vet.id}")).text
    assert f'data-editing="{vet.id}"' in shown and 'value="Call the vet"' in shown
    assert 'value="2026-10-21" checked' in shown  # Today is its day
    for chip in ("Today", "Tomorrow", "The weekend", "Next week", "No date", "Pick a day"):
        assert f"{chip}<" in shown or f">{chip}" in shown
    assert f'hx-post="{person_url(wall)}/move"' in shown


async def test_saved_words_and_day_change_the_task_and_undo_puts_them_back(
    wall: Scenario,
) -> None:
    vet = await task(wall, "Erin", "Call the vet", due=WED)
    board = wall.app.services.get(keys.taskboard)
    saved = (await post(wall, f"{person_url(wall)}/move", op="edit", task=str(vet.id),
                        title="Call the vet about Mimi", due="none", time="")).text  # fmt: skip
    changed = board.get(vet.id)
    assert (changed.title, changed.due_on) == ("Call the vet about Mimi", None)
    assert "Call the vet about Mimi saved." in saved and 'data-undo-for="8"' in saved
    await post(wall, f"{person_url(wall)}/move", op="undo_edit", task=str(vet.id),
               title="Call the vet", due=WED.isoformat(), time="none")  # fmt: skip
    back = board.get(vet.id)
    assert (back.title, back.due_on) == ("Call the vet", WED)


async def test_a_picked_day_and_a_time(wall: Scenario) -> None:
    vet = await task(wall, "Erin", "Call the vet")
    await post(wall, f"{person_url(wall)}/move", op="edit", task=str(vet.id),
               title="Call the vet", due="none", pick="2026-10-30", time="14:30")  # fmt: skip
    changed = wall.app.services.get(keys.taskboard).get(vet.id)
    assert (changed.due_on, changed.due_time) == (date(2026, 10, 30), time(14, 30))


async def test_a_repeating_chore_moves_this_time_only(wall: Scenario) -> None:
    sweep = await task(wall, "Erin", "Sweep", chore=True, due=WED)
    shown = (await get(wall, f"{person_url(wall)}?edit={sweep.id}")).text
    assert "this time only" in shown
    await post(wall, f"{person_url(wall)}/move", op="edit", task=str(sweep.id),
               title="Sweep", due=THU.isoformat(), time="")  # fmt: skip
    moved = wall.app.services.get(keys.taskboard).get(sweep.id)
    assert moved.due_on == THU and moved.repeats  # still repeating


async def test_on_the_together_page_too(wall: Scenario) -> None:
    vac = await task(wall, "Erin", "Vacuum maintenance", both="shared")
    shown = (await get(wall, f"/wall/view/together?edit={vac.id}")).text
    assert f'data-editing="{vac.id}"' in shown
    await post(wall, "/wall/view/together/move", op="edit", task=str(vac.id),
               title="Vacuum filters", due=THU.isoformat(), time="")  # fmt: skip
    changed = wall.app.services.get(keys.taskboard).get(vac.id)
    assert (changed.title, changed.due_on) == ("Vacuum filters", THU)


async def test_nonsense_changes_nothing(wall: Scenario) -> None:
    vet = await task(wall, "Erin", "Call the vet", due=WED)
    await post(wall, f"{person_url(wall)}/move", op="edit", task=str(vet.id),
               title="", due="not a day", time="25:99")  # fmt: skip
    same = wall.app.services.get(keys.taskboard).get(vet.id)
    assert (same.title, same.due_on, same.due_time) == ("Call the vet", WED, None)
