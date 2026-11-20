"""WL5b: the wall's List, Dish and Note views. The scenario's day is Wednesday 21 October
2026, 9 am, Los Angeles."""

from __future__ import annotations

import re
from datetime import timedelta

import httpx

from tests.fixtures.cookbook import TITLE, load, recipe
from tests.fixtures.web import web_client
from tests.integration.test_wall_screen import frame, task, wall, words
from tests.scenarios.harness import Scenario
from themi import clock
from themi.core import keys

__all__ = ["wall"]  # the fixture


async def csrf(client: httpx.AsyncClient) -> str:
    found = re.search(r'"X-CSRF-Token": "([^"]+)"', (await client.get("/wall")).text)
    assert found
    return found[1]


async def get(s: Scenario, path: str) -> httpx.Response:
    async with web_client(s) as client:
        await frame(s, client)
        return await client.get(path, headers={"HX-Request": "true"})


async def post(s: Scenario, path: str, **data: str | list[str]) -> httpx.Response:
    async with web_client(s) as client:
        await frame(s, client)
        token = await csrf(client)
        return await client.post(
            path, data=data, headers={"X-CSRF-Token": token, "HX-Request": "true"}
        )


def board(s: Scenario):
    return s.app.services.get(keys.taskboard)


def audit(s: Scenario) -> list[str]:
    rows = s.app.db.query(
        "SELECT detail FROM action_audit WHERE category = 'wall_tap' AND event = 'staged'"
    )
    return [r["detail"] for r in rows]


# ----- List --------------------------------------------------------------------------


async def test_more_on_the_list_opens_the_whole_list_in_order(wall: Scenario) -> None:
    day = wall.today()
    for title, due in (("Someday", None), ("Vet", day), ("Mail", day + timedelta(days=2))):
        await task(wall, "Erin", title, due=due)
    await task(wall, "Erin", "Old one", due=day - timedelta(days=3))
    erin = wall.member("Erin")
    page = (await get(wall, "/wall")).text
    assert f'hx-get="/wall/view/list/todo/{erin.id}"' in page
    view = await get(wall, f"/wall/view/list/todo/{erin.id}")
    rows = re.findall(r'<span class="wall-title">([^<]+)</span>', view.text)
    assert rows == ["Old one", "Vet", "Mail", "Someday"]
    assert "Erin&#39;s to-do list" in view.text and "from Sunday" in view.text


async def test_tapping_an_items_words_offers_its_changes(wall: Scenario) -> None:
    vet = await task(wall, "Erin", "Call the vet")
    view = await get(wall, f"/wall/view/list/todo/{wall.member('Erin').id}?open={vet.id}")
    menu = view.text[view.text.index('class="sheet-menu"') :]
    menu = words(menu[menu.index(">") + 1 :])
    assert menu.startswith(
        "Tomorrow Next week Give to Husband Make it a family to-do Change the words"
    )


async def test_tomorrow_next_week_give_family_and_words(wall: Scenario) -> None:
    erin, husband = wall.member("Erin"), wall.member("Husband")
    path = f"/wall/view/list/todo/{erin.id}"
    a = await task(wall, "Erin", "Call the vet")
    b = await task(wall, "Erin", "Book the plumber")
    c = await task(wall, "Erin", "Return library books")
    d = await task(wall, "Erin", "Buy stamps")
    e = await task(wall, "Erin", "Sort photos")
    day = wall.today()
    moved = await post(wall, path, op="tomorrow", id=str(a.id))
    assert moved.headers["HX-Trigger"] == "wall-refresh"
    await post(wall, path, op="nextweek", id=str(b.id))
    await post(wall, path, op="give", id=str(c.id), to=str(husband.id))
    await post(wall, path, op="family", id=str(d.id))
    reworded = await post(wall, path, op="words", id=str(e.id), text="Sort the summer photos")
    assert board(wall).get(a.id).due_on == day + timedelta(days=1)
    assert board(wall).get(b.id).due_on == day + timedelta(days=7)
    assert board(wall).get(c.id).assignee == husband.id
    assert board(wall).get(d.id).shared
    assert board(wall).get(e.id).title == "Sort the summer photos"
    assert "Sort the summer photos" in reworded.text
    assert audit(wall) == [
        "Call the vet: tomorrow on the wall",
        "Book the plumber: next week on the wall",
        "Give Return library books to Husband on the wall",
        "Buy stamps: a family to-do on the wall",
        "Reword Sort photos as Sort the summer photos on the wall",
    ]


async def test_adding_and_ticked_off_lately(wall: Scenario) -> None:
    erin = wall.member("Erin")
    done = await task(wall, "Erin", "Water the plants")
    await board(wall).complete(done.id, erin)
    path = f"/wall/view/list/todo/{erin.id}"
    added = await post(wall, path, op="add", text="Fix the gate")
    [made] = [t for t in board(wall).open_for(erin) if t.title == "Fix the gate"]
    assert made.assignee == erin.id and not made.shared
    assert "Fix the gate" in added.text and "Ticked off lately (1)" in added.text
    family = await post(wall, "/wall/view/list/todo/family", op="add", text="Unjam the vacuum")
    [shared] = [t for t in board(wall).open_for(erin) if t.title == "Unjam the vacuum"]
    assert shared.shared and "Unjam the vacuum" in family.text


async def test_a_change_to_something_not_on_that_list_does_nothing(wall: Scenario) -> None:
    hers = await task(wall, "Erin", "Erin's thing")
    path = f"/wall/view/list/todo/{wall.member('Husband').id}"
    await post(wall, path, op="tomorrow", id=str(hers.id))
    assert board(wall).get(hers.id).due_on is None and audit(wall) == []


async def test_the_grocery_list_view(wall: Scenario) -> None:
    groceries = wall.app.services.get(keys.groceries)
    erin = wall.member("Erin")
    groceries.add(["dried mango", "grapes"], by=erin)
    page = (await get(wall, "/wall")).text
    assert 'hx-get="/wall/view/list/groceries"' in page
    view = await get(wall, "/wall/view/list/groceries")
    assert re.findall(r'<span class="wall-title">([^<]+)</span>', view.text) == [
        "Dried mango",
        "Grapes",
    ]
    [mango] = [g for g in groceries.needed() if g.name == "dried mango"]
    await post(wall, "/wall/view/list/groceries", op="bought", id=str(mango.id))
    assert [g.name for g in groceries.needed()] == ["grapes"]
    added = await post(wall, "/wall/view/list/groceries", op="add", text="Oat milk")
    staged = wall.app.db.one(
        "SELECT status FROM pending_actions WHERE category = 'grocery_list_add'"
    )
    assert staged is not None and "oat milk" in added.text.lower()


# ----- Dish --------------------------------------------------------------------------


def soup(s: Scenario) -> int:
    """The cookbook with Bean Soup, and Bean Soup on the household's Things to cook."""
    blocks = [
        ("T", TITLE),
        ("H1", TITLE),
        ("H1", "Entrees"),
        *recipe("Bean Soup", ["1 can white beans", "2 cups broth", "1 onion"], ["Simmer."]),
    ]
    load(s.app.services, blocks)
    lists = s.app.services.get(keys.lists)
    erin = s.member("Erin")
    cook = lists.create(erin, "Things to cook", personal=False)
    lists.add(cook, ["Bean soup", "Creami prep"], erin)
    nl = lists.get(cook.id, erin)
    assert nl is not None
    return nl.open_items[0].id


async def test_a_dish_shows_its_ingredients_to_tick(wall: Scenario) -> None:
    item = soup(wall)
    page = (await get(wall, "/wall")).text
    assert f'hx-get="/wall/view/dish/{item}"' in page
    view = await get(wall, f"/wall/view/dish/{item}")
    names = re.findall(r'name="have" value="([^"]+)"', view.text)
    assert names == ["white beans", "broth", "onion"]
    assert "Husband is cooking" in view.text and "Erin is cooking" in view.text


async def test_add_the_rest_adds_only_whats_missing(wall: Scenario) -> None:
    item = soup(wall)
    groceries = wall.app.services.get(keys.groceries)
    groceries.add(["broth"], by=wall.member("Erin"))
    view = await post(wall, f"/wall/view/dish/{item}/add", have=["onion"])
    row = wall.app.db.one("SELECT payload FROM pending_actions WHERE category = 'grocery_list_add'")
    assert row is not None and '"items": ["white beans"]' in row["payload"]
    assert "white beans" in view.text.lower()


async def test_a_dish_without_a_recipe_is_the_item_alone(wall: Scenario) -> None:
    soup(wall)
    lists = wall.app.services.get(keys.lists)
    erin = wall.member("Erin")
    [nl] = [n for n in lists.visible(erin) if n.name == "Things to cook"]
    creami = next(i for i in nl.open_items if i.name == "Creami prep")
    view = await get(wall, f"/wall/view/dish/{creami.id}")
    assert "no recipe for this" in view.text and 'name="have"' not in view.text
    assert "is cooking" not in view.text


# ----- Note --------------------------------------------------------------------------


async def bins(s: Scenario, both: bool = True) -> int:
    yesterday = s.today() - timedelta(days=1)
    made = await task(
        s, "Erin", "Bring bins in", due=yesterday, chore=True, both="either" if both else ""
    )
    return made.id


async def test_the_note_view_says_why_and_offers_its_answers(wall: Scenario) -> None:
    await bins(wall)
    page = (await get(wall, "/wall")).text
    assert 'hx-get="/wall/view/note"' in page
    view = words((await get(wall, "/wall/view/note")).text)
    assert "It's done Later tonight In the morning" in view
    assert (
        "Why this note: Bring bins in was due yesterday and is still open (either of you)." in view
    )


async def test_its_done_asks_who_and_ticks_it_for_them(wall: Scenario) -> None:
    task_id = await bins(wall)
    asked = await post(wall, "/wall/view/note", answer="done")
    assert "Who did it?" in asked.text and "Both of us" in asked.text
    husband = wall.member("Husband")
    thanked = await post(wall, "/wall/view/note", answer="done", by=str(husband.id))
    assert "Thank you, Husband." in thanked.text
    assert [r.done_by for r in board(wall).runs(task_id)] == [husband.id]
    assert (await get(wall, "/wall/view/note")).text == ""


async def test_later_tonight_brings_the_note_back_at_nine(wall: Scenario) -> None:
    await bins(wall)
    clock.advance(timedelta(hours=10, minutes=42))  # 7:42 pm
    said = await post(wall, "/wall/view/note", answer="later")
    assert "comes back around 9 pm" in said.text
    assert "still waiting" not in (await get(wall, "/wall/part/note")).text
    clock.advance(timedelta(hours=1, minutes=20))  # 9:02 pm
    assert "still waiting" in (await get(wall, "/wall/part/note")).text


async def test_in_the_morning_leaves_it_for_the_morning_message(wall: Scenario) -> None:
    task_id = await bins(wall)
    clock.advance(timedelta(hours=10, minutes=42))
    await post(wall, "/wall/view/note", answer="morning")
    assert "still waiting" not in (await get(wall, "/wall/part/note")).text
    clock.advance(timedelta(hours=12))  # 7:42 am tomorrow
    summary = wall.app.services.get(keys.day_summary)
    erin = wall.member("Erin")
    assert task_id in [t.id for t in summary.due(erin, summary.today(erin))]
    assert board(wall).get(task_id).status == "open"
