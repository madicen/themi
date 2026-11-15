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


# ----- F44b (bug #210): weigh a Tbsp of a spice, not a cup ------------------------------


def cookbook_recipe(scenario: Scenario, name: str, lines: list[str]) -> int:
    recipe_id = web_recipe(scenario, name, lines)
    scenario.app.db.execute("UPDATE recipes SET source = 'doc' WHERE id = ?", (recipe_id,))
    return recipe_id


def titles(scenario: Scenario) -> list[str]:
    return [t["title"] for t in tasks(scenario) if t["status"] == "open"]


async def test_bug_210_a_spice_used_by_the_teaspoon_is_weighed_by_the_tablespoon(
    scenario: Scenario, weights: GramWeights
) -> None:
    cookbook_recipe(scenario, "Pumpkin Pie", ["½ tsp ground nutmeg", "1 cup sugar"])
    cookbook_recipe(scenario, "Alfredo Sauce", ["¼ tsp ground nutmeg"])
    cookbook_recipe(scenario, "Bechamel Sauce", ["Pinch of ground nutmeg"])
    weights.record("ground nutmeg", "wanted")
    await weights.look_up()
    assert titles(scenario) == ["Weigh 1 tablespoon of ground nutmeg when you're next cooking"]
    (task,) = tasks(scenario)
    assert "Spoon ground nutmeg into a 1 tablespoon measure and level it off" in task["steps"]


async def test_cups_or_a_big_volume_still_weigh_a_cup(
    scenario: Scenario, weights: GramWeights
) -> None:
    cookbook_recipe(scenario, "Bread", ["1 tsp teff flour", "2 cups teff flour"])
    cookbook_recipe(scenario, "Soup", ["250 ml oat cream"])
    cookbook_recipe(scenario, "Dressing", ["15 ml rice vinegar"])
    for name in ("teff flour", "oat cream", "rice vinegar"):
        weights.record(name, "wanted")
    await weights.look_up()
    assert sorted(titles(scenario)) == [
        "Weigh 1 cup of oat cream when you're next cooking",
        "Weigh 1 cup of teff flour when you're next cooking",
        "Weigh 1 tablespoon of rice vinegar when you're next cooking",
    ]


async def test_one_of_a_counted_thing_is_singular(scenario: Scenario, weights: GramWeights) -> None:
    cookbook_recipe(scenario, "Alfredo Sauce", ["2 garlic cloves, peeled and left whole"])
    weights.record("garlic cloves", "wanted")
    await weights.look_up()
    assert titles(scenario) == ["Weigh one garlic clove"]


def test_one_of() -> None:
    from themi_home.gram_weights import one_of

    for plural, single in [("garlic cloves", "garlic clove"), ("large eggs", "large egg"),
                           ("bay leaves", "bay leaf"), ("cherry tomatoes", "cherry tomato"),
                           ("strawberries", "strawberry"), ("hummus", "hummus"),
                           ("onion", "onion"), ("molasses", "molasses")]:  # fmt: skip
        assert one_of(plural) == single


async def test_an_open_cup_task_becomes_the_tablespoon_one_once(
    scenario: Scenario, weights: GramWeights
) -> None:
    """The Pi's task 111, made before the fix: renamed in place, no new task."""
    board = scenario.app.services.maybe(keys.taskboard)
    assert board is not None
    cookbook_recipe(scenario, "Pumpkin Pie", ["½ tsp ground nutmeg"])
    erin = scenario.member("Erin")
    steps = [
        "Spoon ground nutmeg into a 1 cup measure and level it off",
        "Weigh it on the kitchen scale",
        "Tell me the grams",
    ]
    title = "Weigh 1 cup of ground nutmeg when you're next cooking"
    old = await board.create(erin, title, "physical", 1, importance="low", steps=steps)
    weights.record("ground nutmeg", "wanted")
    scenario.app.db.execute(
        "UPDATE gram_weights_meta SET task_id = ? WHERE key = ?", (old.id, key("ground nutmeg"))
    )
    await weights.look_up()
    await weights.look_up()
    assert [(t["id"], t["title"]) for t in tasks(scenario)] == [
        (old.id, "Weigh 1 tablespoon of ground nutmeg when you're next cooking")
    ]


async def test_a_tablespoon_weighed_is_saved_as_a_tablespoon(
    scenario: Scenario, weights: GramWeights
) -> None:
    cookbook_recipe(scenario, "Pumpkin Pie", ["½ tsp ground nutmeg"])
    weights.record("ground nutmeg", "wanted")
    await weights.look_up()
    scenario.primary.queue_tool_call(
        "weighed_gram_weight",
        {"ingredient": "ground nutmeg", "amount": 1, "unit": "tbsp", "grams": 7},
    )
    scenario.primary.queue_text("Saved.")
    await scenario.say("Erin", "The tablespoon of nutmeg was 7 g")
    assert weights.book().grams("ground nutmeg", 1, "tbsp") == 7
    assert titles(scenario) == []
