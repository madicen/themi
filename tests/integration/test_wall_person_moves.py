"""F64i (Michael's idea #274): on a person's page on the wall, a chore or to-do can be put in
their own order, given to someone else (or made a family to-do), or deleted, with an Undo.
The scenario's day is Wednesday 21 October 2026, 9 am, Los Angeles."""

from __future__ import annotations

import re

from tests.integration.test_wall_list_views import post
from tests.integration.test_wall_screen import column, screen, task, wall
from tests.integration.test_wall_views import get
from tests.scenarios.harness import Scenario
from themi.core import keys

__all__ = ["wall"]  # the fixture


def todo_titles(html: str) -> list[str]:
    box = re.search(r'<section class="page-box page-todo"[^>]*>(.*?)</section>', html, re.S)
    assert box, html
    return re.findall(r'<span class="wall-title">([^<]+)</span>', box[1])


async def page(s: Scenario, name: str = "Erin") -> str:
    return (await get(s, f"/wall/view/person/{s.member(name).id}")).text


async def move(s: Scenario, name: str = "Erin", **form: str) -> str:
    return (await post(s, f"/wall/view/person/{s.member(name).id}/move", **form)).text


async def test_the_rows_can_be_held_and_the_targets_are_there(wall: Scenario) -> None:
    await task(wall, "Erin", "Vet")
    shown = await page(wall)
    assert 'data-drag="todos"' in shown and 'data-drop="todos"' in shown
    assert 'class="drag-to tone-' in shown and 'data-to="family"' in shown
    assert f'data-to="{wall.member("Husband").id}"' in shown
    assert (
        'class="drag-delete"' in shown
        and f'data-moves="/wall/view/person/{wall.member("Erin").id}/move"' in shown
    )


async def test_a_to_do_dragged_up_keeps_its_place_on_the_page_and_the_column(
    wall: Scenario,
) -> None:
    vet, _, gate = [await task(wall, "Erin", t) for t in ("Vet", "Mail", "Gate")]
    before = todo_titles(await page(wall))
    assert before == ["Vet", "Mail", "Gate"]
    after = await move(wall, op="move", task=str(gate.id), before=str(vet.id))
    assert todo_titles(after) == ["Gate", "Vet", "Mail"]
    await move(wall, op="move", task=str(vet.id), before="")  # to the end
    assert todo_titles(await page(wall)) == ["Gate", "Mail", "Vet"]
    col = column(await screen(wall), f"m{wall.member('Erin').id}")
    assert col.index("Gate") < col.index("Mail") < col.index("Vet")  # the home screen too
    new = await task(wall, "Erin", "Shelf")
    assert todo_titles(await page(wall))[-1] == "Shelf"  # the unordered ones after
    assert new.id


async def test_dropped_on_someone_it_is_theirs_and_they_hear(wall: Scenario) -> None:
    vet = await task(wall, "Erin", "Vet")
    husband = wall.member("Husband")
    shown = await move(wall, op="give", task=str(vet.id), to=str(husband.id))
    assert "Vet" not in todo_titles(shown)
    board = wall.app.services.get(keys.taskboard)
    assert board.get(vet.id).assignee == husband.id
    mail = await task(wall, "Erin", "Mail")
    await move(wall, op="give", task=str(mail.id), to="family")
    moved = board.get(mail.id)
    assert moved.shared


async def test_dropped_on_delete_it_goes_and_undo_brings_it_back(wall: Scenario) -> None:
    vet = await task(wall, "Erin", "Vet")
    gone = await move(wall, op="delete", task=str(vet.id))
    board = wall.app.services.get(keys.taskboard)
    assert board.get(vet.id).status == "cancelled"  # its record kept
    assert "Vet deleted." in gone and 'data-undo-for="8"' in gone and ">Undo</button>" in gone
    back = await move(wall, op="undo_delete", task=str(vet.id))
    assert board.get(vet.id).status == "open" and "Vet" in todo_titles(back)


async def test_a_chore_dropped_on_delete_asks_first(wall: Scenario) -> None:
    sweep = await task(wall, "Erin", "Sweep", chore=True, due=None)
    board = wall.app.services.get(keys.taskboard)
    await board.reschedule(sweep.id, wall.app.services.get(keys.taskboard)._today())
    asked = await move(wall, op="delete", task=str(sweep.id))
    assert "Sweep repeats. Stop it repeating, or just this time?" in asked
    assert board.get(sweep.id).status == "open"  # nothing yet
    said = await move(wall, op="skip", task=str(sweep.id))
    skipped = board.get(sweep.id)
    assert skipped.status == "open" and skipped.due_on > board._today()  # just this time
    assert "Sweep skipped this time." in said
    today = board._today().isoformat()
    assert f'"due": "{today}"' in said  # its Undo knows the day it was
    await move(wall, op="undo_skip", task=str(sweep.id), due=today)
    assert board.get(sweep.id).due_on == board._today()
    mop = await task(wall, "Erin", "Mop", chore=True)
    await board.reschedule(mop.id, board._today())
    await move(wall, op="stop", task=str(mop.id))
    assert board.get(mop.id).status == "cancelled"  # stopped repeating


async def test_someone_elses_task_cant_be_moved_from_this_page(wall: Scenario) -> None:
    theirs = await task(wall, "Husband", "Tyres")
    await move(wall, op="delete", task=str(theirs.id))
    await move(wall, op="give", task=str(theirs.id), to="family")
    board = wall.app.services.get(keys.taskboard)
    assert board.get(theirs.id).status == "open" and not board.get(theirs.id).shared
