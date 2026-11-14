"""GW4: weights nobody could find online become small weighing tasks: only for recipes the
family cooked or keeps in the cookbook, one per ingredient, at most 3 open. What they weigh
goes in the guide and closes the task. The clock starts Wednesday 21 October 2026, 9 am."""

from __future__ import annotations

import pytest

from tests.fixtures.cookbook import load
from tests.fixtures.weights_guide import WEIGHTS_GUIDE
from tests.scenarios.harness import Scenario
from themi.core import keys
from themi_home.gram_weights import GramWeights, key


@pytest.fixture
def weights(scenario: Scenario) -> GramWeights:
    guides = scenario.app.services.maybe(keys.guides)
    assert guides is not None
    guides.save(scenario.member("Erin"), "Weights of Common Ingredients", WEIGHTS_GUIDE,
                personal=False)  # fmt: skip
    found = scenario.app.services.maybe(GramWeights)
    assert found is not None
    return found


def tasks(scenario: Scenario) -> list[dict]:
    return scenario.app.db.query("SELECT * FROM tasks ORDER BY id")


def web_recipe(scenario: Scenario, name: str, lines: list[str]) -> int:
    import json

    return scenario.app.db.execute(
        "INSERT INTO recipes (key, source, url, name, ingredients, created_at, updated_at) "
        "VALUES (?, 'web', 'https://cooks.example/x', ?, ?, '2026-10-21', '2026-10-21')",
        (f"web:{name}", name, json.dumps([{"text": t, "group": ""} for t in lines])),
    )


async def test_a_cookbook_recipes_missing_weight_becomes_a_task(
    scenario: Scenario, weights: GramWeights
) -> None:
    load(scenario.app.services)
    weights.record("unsweetened almond milk", "wanted")  # the pancakes': nobody found it
    await weights.look_up()
    made = [t for t in tasks(scenario) if "almond milk" in t["title"]]
    assert len(made) == 1
    task = made[0]
    assert task["title"] == "Weigh 1 cup of unsweetened almond milk when you're next cooking"
    assert (task["kind"], task["effort"], task["importance"], task["due_on"]) == (
        "physical",
        1,
        "low",
        None,
    )
    assert "Weigh it on the kitchen scale" in task["steps"]
    meta = weights.meta(key("almond milk"))
    assert meta is not None and meta["task_id"] == task["id"]
    await weights.look_up()
    assert len([t for t in tasks(scenario) if "almond milk" in t["title"]]) == 1  # one only


async def test_browsing_a_web_recipe_makes_no_chores(
    scenario: Scenario, weights: GramWeights
) -> None:
    web_recipe(scenario, "Teff Pancakes", ["1 cup teff flour"])
    weights.record("teff flour", "wanted")
    await weights.look_up()
    assert tasks(scenario) == []


async def test_a_cooked_web_recipe_does(scenario: Scenario, weights: GramWeights) -> None:
    recipe_id = web_recipe(scenario, "Teff Pancakes", ["1 cup teff flour"])
    erin = scenario.member("Erin")
    scenario.app.db.execute(
        "INSERT INTO cooking_sessions (member_id, recipe_id, phase, started_at, last_tap_at) "
        "VALUES (?, ?, 'done', '2026-10-20', '2026-10-20')",
        (erin.id, recipe_id),
    )
    weights.record("teff flour", "wanted")
    await weights.look_up()
    assert [t["title"] for t in tasks(scenario)] == [
        "Weigh 1 cup of teff flour when you're next cooking"
    ]


async def test_at_most_three_open(scenario: Scenario, weights: GramWeights) -> None:
    web_recipe(scenario, "Flours", [f"1 cup {n} flour" for n in ("teff", "rye", "oat", "spelt")])
    scenario.app.db.execute("UPDATE recipes SET source = 'doc'")  # kept in the cookbook
    for name in ("teff flour", "rye flour", "oat flour", "spelt flour"):
        weights.record(name, "wanted")
    await weights.look_up()
    assert len(tasks(scenario)) == 3
    first = tasks(scenario)[0]
    board = scenario.app.services.get(keys.taskboard)
    await board.complete(first["id"], scenario.member("Erin"))  # done without saying grams
    await weights.look_up()
    assert len(tasks(scenario)) == 4  # a slot opened


async def test_a_reply_saves_the_weight_and_closes_the_task(
    scenario: Scenario, weights: GramWeights
) -> None:
    web_recipe(scenario, "Teff Pancakes", ["1 cup teff flour"])
    scenario.app.db.execute("UPDATE recipes SET source = 'doc'")
    weights.record("teff flour", "wanted")
    await weights.look_up()
    (task,) = tasks(scenario)
    scenario.primary.queue_tool_call(
        "weighed_gram_weight",
        {"ingredient": "teff flour", "amount": 1, "unit": "cup", "grams": 92},
    )
    replies = await scenario.say("Erin", "A cup of teff flour was 92 grams")
    assert replies == [
        "Saved: 1 Cup Teff Flour: Weight in Grams 92g. Teff Pancakes now show grams for it."
    ]
    assert weights.book().grams("teff flour", 1, "cup") == 92
    meta = weights.meta(key("teff flour"))
    assert meta is not None and meta["source"] == "weighed" and meta["task_id"] is None
    assert scenario.app.db.scalar("SELECT status FROM tasks WHERE id = ?", (task["id"],)) == "done"


async def test_a_weight_that_cant_be_right_is_asked_about(
    scenario: Scenario, weights: GramWeights
) -> None:
    scenario.primary.queue_tool_call(
        "weighed_gram_weight",
        {"ingredient": "teff flour", "amount": 1, "unit": "cup", "grams": 920},
    )
    scenario.primary.queue_text("920 g for a cup seems a lot. Could you check the scale?")
    await scenario.say("Erin", "A cup of teff flour was 920 grams")
    assert not weights.book().has("teff flour")


async def test_a_weight_filled_another_way_cancels_its_task(
    scenario: Scenario, weights: GramWeights
) -> None:
    web_recipe(scenario, "Teff Pancakes", ["1 cup teff flour"])
    scenario.app.db.execute("UPDATE recipes SET source = 'doc'")
    weights.record("teff flour", "wanted")
    await weights.look_up()
    (task,) = tasks(scenario)
    guide = weights.guide()
    guides = scenario.app.services.maybe(keys.guides)
    assert guide is not None and guides is not None
    guides.append_line(guide.id, "1 cup teff flour = 92 g")  # typed on the Guides page
    await weights.look_up()
    status = scenario.app.db.scalar("SELECT status FROM tasks WHERE id = ?", (task["id"],))
    assert status == "cancelled"
    assert weights.meta(key("teff flour")) is None  # the family's own line now


async def test_a_lookup_that_fills_it_cancels_its_task(
    scenario: Scenario, weights: GramWeights
) -> None:
    web_recipe(scenario, "Teff Pancakes", ["1 cup teff flour"])
    scenario.app.db.execute("UPDATE recipes SET source = 'doc'")
    weights.record("teff flour", "wanted")
    await weights.look_up()
    (task,) = tasks(scenario)
    assert await weights.save(scenario.member("Erin"), "teff flour", 1, "cup", 92, "web",
                              agrees=2)  # fmt: skip
    status = scenario.app.db.scalar("SELECT status FROM tasks WHERE id = ?", (task["id"],))
    assert status == "cancelled"
