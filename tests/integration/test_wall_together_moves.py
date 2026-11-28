"""F65j (Michael's bug #275, "can't reorder the family tasks on the wall frame"): on the
Together page, a shared to-do or an either-of-you chore can be put in the family's order,
given to one person, or deleted, with an Undo, as F64i's person page does. The scenario's
day is Wednesday 21 October 2026, 9 am, Los Angeles."""

from __future__ import annotations

import re

from tests.integration.test_wall_list_views import post
from tests.integration.test_wall_screen import column, screen, task, wall
from tests.integration.test_wall_views import get
from tests.scenarios.harness import Scenario
from themi.core import keys

__all__ = ["wall"]  # the fixture


def family_titles(html: str) -> list[str]:
    box = re.search(r'<ul data-drop="family">(.*?)</ul>', html, re.S)
    assert box, html
    return re.findall(r'<span class="wall-title">([^<]+)</span>', box[1])


async def page(s: Scenario) -> str:
    return (await get(s, "/wall/view/together")).text


async def move(s: Scenario, **form: str) -> str:
    return (await post(s, "/wall/view/together/move", **form)).text


async def shared(s: Scenario, *titles: str) -> list:
    return [await task(s, "Erin", t, both="shared") for t in titles]


async def test_the_rows_can_be_held_and_the_targets_are_there(wall: Scenario) -> None:
    await shared(wall, "Vacuum maintenance")
    shown = await page(wall)
    assert 'data-drag="family"' in shown and 'data-drop="family"' in shown
    assert 'data-moves="/wall/view/together/move"' in shown and 'class="drag-delete"' in shown
    for name in ("Erin", "Husband"):
        assert f'data-to="{wall.member(name).id}"' in shown


async def test_bug_275_the_family_list_keeps_the_order_it_was_dragged_to(wall: Scenario) -> None:
    vac, mimi, gas = await shared(wall, "Vacuum", "Mimis box", "Gas")
    assert family_titles(await page(wall)) == ["Vacuum", "Mimis box", "Gas"]
    after = await move(wall, op="move", task=str(gas.id), before=str(vac.id))
    assert family_titles(after) == ["Gas", "Vacuum", "Mimis box"]
    col = column(await screen(wall), "together")
    assert col.index("Gas") < col.index("Vacuum") < col.index("Mimi")  # the home screen too
    await shared(wall, "Unjam the vacuum")
    assert family_titles(await page(wall))[-1] == "Unjam the vacuum"
    assert mimi.id


async def test_dropped_on_a_person_it_is_theirs_alone(wall: Scenario) -> None:
    (vac,) = await shared(wall, "Vacuum")
    husband = wall.member("Husband")
    shown = await move(wall, op="give", task=str(vac.id), to=str(husband.id))
    assert "Vacuum" not in shown.split("Done today")[0].split("Family to-do")[1]
    moved = wall.app.services.get(keys.taskboard).get(vac.id)
    assert moved.assignee == husband.id and not moved.shared


async def test_dropped_on_delete_it_goes_and_undo_brings_it_back(wall: Scenario) -> None:
    (vac,) = await shared(wall, "Vacuum")
    board = wall.app.services.get(keys.taskboard)
    gone = await move(wall, op="delete", task=str(vac.id))
    assert board.get(vac.id).status == "cancelled"
    assert "Vacuum deleted." in gone and 'data-undo-for="8"' in gone
    back = await move(wall, op="undo_delete", task=str(vac.id))
    assert board.get(vac.id).status == "open" and "Vacuum" in family_titles(back)


async def test_made_a_family_to_do_from_a_persons_page_goes_last(wall: Scenario) -> None:
    await shared(wall, "Vacuum", "Gas")
    page_first = await move(wall, op="move", task=str((await shared(wall, "Bins"))[0].id),
                            before="")  # fmt: skip
    assert family_titles(page_first)[-1] == "Bins"
    mail = await task(wall, "Erin", "Mail")
    await post(wall, f"/wall/view/person/{wall.member('Erin').id}/move", op="give",
               task=str(mail.id), to="family")  # fmt: skip
    assert family_titles(await page(wall))[-1] == "Mail"
