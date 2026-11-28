"""WL9c: the columns say where a tap goes, and a tick folds away after ten minutes. The
scenario's day is Wednesday 21 October 2026, 9 am, Los Angeles."""

from __future__ import annotations

import re
from datetime import timedelta

from tests.fixtures.web import web_client
from tests.integration.test_wall_screen import column, frame, screen, task, wall, words
from tests.integration.test_wall_taps import tap
from tests.scenarios.harness import Scenario
from themi import clock

__all__ = ["wall"]  # the fixture


async def ticked(s: Scenario, key: str, **more: str) -> None:
    async with web_client(s) as client:
        await frame(s, client)
        await tap(s, client, key, **more)


async def test_a_tick_stays_struck_through_for_ten_minutes_then_folds(wall: Scenario) -> None:
    errand = await task(wall, "Erin", "Process the mail")
    await task(wall, "Erin", "Call the vet")
    await ticked(wall, f"task-{errand.id}")
    erin = f"m{wall.member('Erin').id}"
    clock.advance(timedelta(minutes=9))
    shown = column(await screen(wall), erin)
    assert re.search(rf'class="wall-item done" data-key="task-{errand.id}"', shown)
    assert not re.search(r'class="wall-fold" data-done="[1-9]', shown)  # F65c: one waits, hidden
    clock.advance(timedelta(minutes=2))
    shown = column(await screen(wall), erin)
    assert f"task-{errand.id}" not in shown
    todo = words(shown[shown.index("To-do") :])
    assert "Call the vet" in todo and "✓ 1 done" in todo
    assert "3 done" not in todo


async def test_a_chore_folds_in_its_own_section(wall: Scenario) -> None:
    chores = [
        await task(wall, "Erin", title, due=wall.today(), chore=True)
        for title in ("Refill pet feeders", "Clean the bird cage")
    ]
    await task(wall, "Erin", "Call the vet")
    for chore in chores:
        await ticked(wall, f"task-{chore.id}")
    clock.advance(timedelta(minutes=11))
    shown = words(column(await screen(wall), f"m{wall.member('Erin').id}"))
    chores_part = shown[shown.index("Chores") : shown.index("To-do")]
    assert chores_part.strip() == "Chores ✓ 2 done"
    assert "✓" not in shown[shown.index("To-do") :]
    assert "2 done today" in shown  # the header's count is unchanged


async def test_together_folds_too_never_saying_who_did_more(wall: Scenario) -> None:
    bins = await task(wall, "Erin", "Bring bins in", due=wall.today(), chore=True, both="either")
    await ticked(wall, f"task-{bins.id}", by=str(wall.member("Husband").id))
    assert "Bring bins in Husband did it" in words(column(await screen(wall), "together"))
    clock.advance(timedelta(minutes=11))
    together = words(column(await screen(wall), "together"))
    assert "Bring bins in" not in together and "✓ 1 done" in together
    assert "Husband" not in together


async def test_past_the_top_few_one_line_says_how_many_more(wall: Scenario) -> None:
    from themi_home.wall_view import TODOS_SHOWN  # F60f: 12 now, the frame fits fewer

    for n in range(TODOS_SHOWN + 2):
        await task(wall, "Erin", f"Job {n}")
    erin = wall.member("Erin")
    shown = column(await screen(wall), f"m{erin.id}")
    more = re.search(r'<button type="button" class="wall-more"([^>]*)>([^<]*)</button>', shown)
    assert more and more[2] == "+2 more"
    assert f'hx-get="/wall/view/list/todo/{erin.id}"' in more[1]  # the item menus are there


async def test_each_column_ends_with_where_a_tap_goes(wall: Scenario) -> None:
    page = await screen(wall)
    erin = wall.member("Erin")
    mine = column(page, f"m{erin.id}")
    foot = re.search(
        r'<button type="button" class="wall-col-foot"([^>]*)>(.*?)</button>', mine, re.S
    )
    assert foot and words(foot[2]) == "View full day"
    assert f'hx-get="/wall/view/person/{erin.id}"' in foot[1]
    assert 'class="wall-col-go"' in mine  # the ↗ on the header
    together = column(page, "together")
    foot = re.search(
        r'<button type="button" class="wall-col-foot"([^>]*)>(.*?)</button>', together, re.S
    )
    assert foot and words(foot[2]) == "View shared list"
    head = re.search(r'<button type="button" class="wall-col-head"([^>]*)>', together)
    assert head and 'hx-get="/wall/view/together"' in head[1]  # WL9d's page
