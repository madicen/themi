# ruff: noqa: RUF001
"""RC3a: cooking a recipe with Themi, getting ready: what needs time first, gathering and
prep. The clock starts Wednesday 21 October 2026, 9 am."""

from __future__ import annotations

import pytest

from tests.fixtures.cookbook import load
from tests.scenarios.harness import Scenario
from themi.core import keys

ALFREDO = [
    "cashews", "water", "garlic", "miso", "lemon juice", "salt", "nutmeg", "onion powder",
    "black pepper",
]  # fmt: skip


def items(names: list[str], staples: tuple[str, ...] = ("water", "salt", "black pepper")) -> dict:
    return {
        "lines": [
            {"n": n, "item": item, "quantity": "", "unit": "", "note": "", "optional": False,
             "staple": item in staples}
            for n, item in enumerate(names, start=1)
        ]
    }  # fmt: skip


@pytest.fixture
def cookbook(scenario: Scenario) -> Scenario:
    load(scenario.app.services)
    return scenario


async def show_alfredo(scenario: Scenario) -> None:
    scenario.primary.queue_tool_call("find_recipe", {"query": "alfredo sauce", "section": ""})
    await scenario.say("Erin", "Can you pull up the alfredo sauce?")


def card(scenario: Scenario, name: str = "Erin") -> str:
    return scenario.edits(name)[-1]["text"]


def card_buttons(scenario: Scenario, name: str = "Erin") -> list[str]:
    import json

    markup = scenario.edits(name)[-1].get("reply_markup") or {}
    if isinstance(markup, str):
        markup = json.loads(markup)
    return [b["text"] for row in markup.get("inline_keyboard", []) for b in row]


async def test_alfredo_from_cook_this_to_prep_done(cookbook: Scenario) -> None:
    await show_alfredo(cookbook)
    assert "Cook this" in cookbook.last_buttons("Erin")
    cookbook.primary.queue_structured(items(ALFREDO))
    (first,) = await cookbook.tap("Erin", "Cook this")
    assert first == "Cooking Alfredo Sauce.\nBefore anything else: soak the cashews (10 min)."
    assert cookbook.last_buttons("Erin") == ["Done", "Skip"]
    await cookbook.tap("Erin", "Done")
    gather = card(cookbook)
    assert gather.splitlines()[0] == "Cooking Alfredo Sauce. What it uses (tap each as it's out):"
    assert "> · 1 Cup cashews, soaked in water for at least 10 minutes (130g)" in gather
    await cookbook.tap("Erin", "· cashews")
    assert "> ✓ 1 Cup cashews" in card(cookbook)
    cookbook.primary.queue_structured(
        {
            "jobs": [
                {"text": "Garlic: peel, keep whole", "line": 3, "tool": "knife"},
                {"text": "Tofu: press it", "line": 1, "tool": "knife"},  # not in that line
                {"text": "Lemon juice: measure 1 tsp", "line": 5, "tool": "measure"},
            ]
        }
    )
    await cookbook.tap("Erin", "All here")
    assert card(cookbook) == (
        "Prep for Alfredo Sauce:\n> Garlic: peel, keep whole\n> Lemon juice: measure 1 tsp"
    )
    prompt = cookbook.primary.requests[-1].prompt
    assert prompt.startswith('<data source="recipe Alfredo Sauce">')
    await cookbook.tap("Erin", "Prep done")
    assert card(cookbook) == (
        "Alfredo Sauce: step 1 of 3\n> Drain and discard water from soaked cashews."
    )  # RC3b: on to the steps


async def test_the_prep_is_read_once(cookbook: Scenario) -> None:
    cooking = cookbook.app.services.maybe(keys.cooking)
    recipes = cookbook.app.services.maybe(keys.recipes)
    assert cooking is not None and recipes is not None
    alfredo = next(r for r in recipes.all() if r.name == "Alfredo Sauce")
    cookbook.primary.queue_structured(items(ALFREDO))
    cookbook.primary.queue_structured(
        {"jobs": [{"text": "Garlic: peel", "line": 3, "tool": "knife"}]}
    )
    member = cookbook.member("Erin")
    first = await cooking.prep_jobs(member, alfredo)
    again = await cooking.prep_jobs(member, alfredo)
    assert first == again == [{"text": "Garlic: peel", "line": 3, "tool": "knife"}]


async def test_an_overnight_soak_offers_tomorrow(cookbook: Scenario) -> None:
    cookbook.primary.queue_tool_call("start_cooking", {"recipe": "chana masala", "scale": ""})
    cookbook.primary.queue_structured(
        {"lines": [{"n": 1, "item": "dried chickpeas", "quantity": "2", "unit": "Cups",
                    "note": "soaked overnight", "optional": False, "staple": False}]}
    )  # fmt: skip
    (first,) = await cookbook.say("Erin", "Let's make the chana masala")
    assert first == (
        "Cooking Chana Masala.\nThis one needs time the night before (soak the dried "
        "chickpeas), so it's a stretch for today."
    )
    assert cookbook.last_buttons("Erin") == ["Cook anyway", "Remind me tomorrow"]
    await cookbook.tap("Erin", "Remind me tomorrow")
    assert card(cookbook).startswith("Chana Masala tomorrow, then: I'll bring it back at 5 pm.")
    await cookbook.advance(hours=31)  # Thursday, 4 pm
    assert not any("as you asked yesterday" in t for t in cookbook.inbox("Erin"))
    sent = await cookbook.advance(hours=1, minutes=5)
    assert any(t.startswith("Chana Masala again, as you asked yesterday.") for t in sent)
    assert cookbook.last_buttons("Erin") == ["Cook this"]


async def test_cook_anyway(cookbook: Scenario) -> None:
    cookbook.primary.queue_tool_call("start_cooking", {"recipe": "chana masala", "scale": ""})
    cookbook.primary.queue_structured(
        {"lines": [{"n": 1, "item": "dried chickpeas", "quantity": "", "unit": "",
                    "note": "", "optional": False, "staple": False}]}
    )  # fmt: skip
    await cookbook.say("Erin", "Let's make the chana masala")
    await cookbook.tap("Erin", "Cook anyway")
    assert card(cookbook).startswith("Cooking Chana Masala. What it uses")


async def test_typing_moves_it_on_with_a_fresh_card(cookbook: Scenario) -> None:
    await show_alfredo(cookbook)
    cookbook.primary.queue_structured(items(ALFREDO))
    await cookbook.tap("Erin", "Cook this")
    calls = len(cookbook.primary.requests)
    (fresh,) = await cookbook.say("Erin", "done")
    assert fresh.startswith("Cooking Alfredo Sauce. What it uses")
    assert card(cookbook) == "(Carried on below.)"  # the old card, without its buttons
    assert len(cookbook.primary.requests) == calls  # no model round for "done"
    replies = await cookbook.say("Erin", "stop cooking")
    assert replies == ["Stopped cooking Alfredo Sauce."]
    assert cookbook.app.services.maybe(keys.cooking).current(cookbook.member("Erin")) is None  # type: ignore[union-attr]


async def test_questions_during_a_session_come_from_the_recipe(cookbook: Scenario) -> None:
    await show_alfredo(cookbook)
    cookbook.primary.queue_structured(items(ALFREDO))
    await cookbook.tap("Erin", "Cook this")
    cookbook.primary.queue_text("From the recipe: 2 garlic cloves, peeled and left whole.")
    await cookbook.say("Erin", "How much garlic?")
    turn = cookbook.primary.requests[-1].messages[0].text
    assert "Cooking now with Themi: Alfredo Sauce (getting ready)" in turn
    assert '<data source="recipe Alfredo Sauce">' in turn
    assert "2 garlic cloves, peeled and left whole" in turn


async def test_someone_elses_card_isnt_theirs_to_tap(cookbook: Scenario) -> None:
    await show_alfredo(cookbook)
    cookbook.primary.queue_structured(items(ALFREDO))
    await cookbook.tap("Erin", "Cook this")
    cooking = cookbook.app.services.maybe(keys.cooking)
    assert cooking is not None
    session = cooking.current(cookbook.member("Erin"))
    assert session is not None
    from themi import clock
    from themi.channels.events import ButtonPress, InboundEvent

    tap = InboundEvent(
        "button", cookbook.member("Husband"), 2, None, clock.now(), 0,
        button=ButtonPress("Done", "cooking", {"session": session.id, "action": "next"}, 1),
    )  # fmt: skip
    await cooking.on_button(tap)
    assert cooking.get(session.id).phase == "ready"  # type: ignore[union-attr]


async def test_a_session_left_alone_ends_quietly(cookbook: Scenario) -> None:
    await show_alfredo(cookbook)
    cookbook.primary.queue_structured(items(ALFREDO))
    await cookbook.tap("Erin", "Cook this")
    before = len(cookbook.inbox("Erin"))
    await cookbook.advance(hours=3, minutes=20)
    await cookbook.run_periodic("cooking.expire")
    row = cookbook.app.db.one("SELECT outcome FROM cooking_sessions")
    assert row == {"outcome": "left"}
    assert len(cookbook.inbox("Erin")) == before  # nothing said about it


# ----- RC3b: the steps -------------------------------------------------------------------

PANCAKES = [
    "white whole wheat flour", "all-purpose flour", "baking powder", "cinnamon", "kosher salt",
    "almond milk", "applesauce", "vanilla extract",
]  # fmt: skip


async def to_the_steps(scenario: Scenario) -> None:
    scenario.primary.queue_tool_call("start_cooking", {"recipe": "pancakes", "scale": ""})
    scenario.primary.queue_structured(items(PANCAKES, staples=("kosher salt",)))
    await scenario.say("Erin", "Let's make the pancakes")
    await scenario.tap("Erin", "Done")  # preheat the oven (to keep them warm)
    scenario.primary.queue_structured({"jobs": []})  # nothing to prep
    await scenario.tap("Erin", "All here")


async def test_pancakes_from_step_one_to_all_done(cookbook: Scenario) -> None:
    await to_the_steps(cookbook)
    assert card(cookbook) == (
        "Pancakes: step 1 of 5\n> If you’d like to keep the pancakes warm between batches, "
        "preheat the oven to 200 °F."
    )
    assert card_buttons(cookbook) == ["Next"]
    await cookbook.tap("Erin", "Next")
    await cookbook.tap("Erin", "Next")
    assert card(cookbook).startswith("Pancakes: step 3 of 5\n> Make a well")
    await cookbook.tap("Erin", "Back")
    assert card(cookbook).startswith("Pancakes: step 2 of 5\n> In the bottom of a large")
    assert card_buttons(cookbook) == ["Back", "Next"]
    for _ in range(3):
        await cookbook.tap("Erin", "Next")
    assert card(cookbook).startswith("Pancakes: step 5 of 5")
    assert card_buttons(cookbook) == ["Back", "All done", "Timer 2 min (2-3)", "Timer 1 min (1-2)"]
    await cookbook.tap("Erin", "All done")
    assert card(cookbook) == "Pancakes, all done. Enjoy it!"
    row = cookbook.app.db.one("SELECT outcome FROM cooking_sessions")
    assert row == {"outcome": "finished"}


async def test_typed_steps(cookbook: Scenario) -> None:
    await to_the_steps(cookbook)
    calls = len(cookbook.primary.requests)
    (two,) = await cookbook.say("Erin", "next")
    assert two.startswith("Pancakes: step 2 of 5")
    (four,) = await cookbook.say("Erin", "go to step 4")
    assert four.startswith("Pancakes: step 4 of 5\n> Heat a large nonstick skillet")
    (peek,) = await cookbook.say("Erin", "What's after this?")
    assert peek.startswith("After this, step 5:\n> Drop the batter")
    (again,) = await cookbook.say("Erin", "repeat")
    assert again.startswith("Pancakes: step 4 of 5")
    assert len(cookbook.primary.requests) == calls  # all without the model


async def test_a_nudge_waits_while_cooking(cookbook: Scenario) -> None:
    from themi.channels.outbox import Priority

    await to_the_steps(cookbook)
    erin = cookbook.member("Erin")
    result = await cookbook.app.outbox.send(
        erin, "The recycling goes out tonight.", priority=Priority.NORMAL, kind="task"
    )
    assert result.status == "queued"
    await cookbook.app.outbox.flush()
    assert "The recycling goes out tonight." not in cookbook.inbox("Erin")
    (_,) = await cookbook.say("Erin", "stop cooking")
    await cookbook.app.outbox.flush()
    assert "The recycling goes out tonight." in cookbook.inbox("Erin")


async def test_a_step_naming_another_recipe_offers_it(cookbook: Scenario) -> None:
    cooking = cookbook.app.services.maybe(keys.cooking)
    recipes = cookbook.app.services.maybe(keys.recipes)
    assert cooking is not None and recipes is not None
    lasagna = next(r for r in recipes.all() if r.name == "Lasagna")
    named = cooking.named_recipes(lasagna, "Top with the Bechamel Sauce and bake.")
    assert [r.name for r in named] == ["Bechamel Sauce"]
    assert cooking.named_recipes(lasagna, "Top with sauce.") == []


# ----- RC3c: timers ----------------------------------------------------------------------


async def to_step_five(scenario: Scenario) -> None:
    await to_the_steps(scenario)
    for _ in range(4):
        await scenario.tap("Erin", "Next")


async def test_two_timers_fire_in_order(cookbook: Scenario) -> None:
    await to_step_five(cookbook)
    assert card_buttons(cookbook) == ["Back", "All done", "Timer 2 min (2-3)", "Timer 1 min (1-2)"]
    (set_one,) = await cookbook.tap("Erin", "Timer 2 min (2-3)")
    assert set_one == "Timer set: 2 min for step 5, done at 9:02 am."
    await cookbook.tap("Erin", "Timer 1 min (1-2)")
    from themi import clock

    clock.advance(__import__("datetime").timedelta(minutes=1, seconds=5))
    await cookbook.run_jobs()
    assert cookbook.inbox("Erin")[-1] == "Time's up: 1 min for step 5 of Pancakes."
    clock.advance(__import__("datetime").timedelta(minutes=1))
    await cookbook.run_jobs()
    assert cookbook.inbox("Erin")[-1] == "Time's up: 2 min for step 5 of Pancakes."


async def test_a_timer_rings_in_quiet_hours(cookbook: Scenario) -> None:
    from datetime import timedelta

    from themi import clock

    clock.advance(timedelta(hours=13, minutes=55))  # 10:55 pm: quiet hours
    await to_step_five(cookbook)
    await cookbook.tap("Erin", "Timer 2 min (2-3)")
    clock.advance(timedelta(minutes=3))
    await cookbook.run_jobs()
    assert cookbook.inbox("Erin")[-1] == "Time's up: 2 min for step 5 of Pancakes."


async def test_a_timer_is_a_stored_job(cookbook: Scenario) -> None:
    await to_step_five(cookbook)
    await cookbook.tap("Erin", "Timer 2 min (2-3)")
    jobs = cookbook.app.db.query("SELECT kind, status FROM job_queue WHERE kind = 'cooking.timer'")
    assert jobs == [{"kind": "cooking.timer", "status": "queued"}]  # kept across a restart


async def test_how_long_left_more_time_and_cancel(cookbook: Scenario) -> None:
    from datetime import timedelta

    from themi import clock

    await to_step_five(cookbook)
    await cookbook.tap("Erin", "Timer 2 min (2-3)")
    clock.advance(timedelta(seconds=30))
    assert await cookbook.say("Erin", "How long left?") == ["2 min left on step 5."]
    assert await cookbook.say("Erin", "add 2 minutes") == [
        "Added 2 min: step 5 is done at 9:04 am."
    ]
    clock.advance(timedelta(minutes=2))
    await cookbook.run_jobs()  # the old end: moved, so nothing yet
    assert not cookbook.inbox("Erin")[-1].startswith("Time's up")
    assert await cookbook.say("Erin", "cancel the timer") == ["Timer cancelled."]
    clock.advance(timedelta(minutes=5))
    await cookbook.run_jobs()
    assert not any(t.startswith("Time's up") for t in cookbook.inbox("Erin"))


async def test_ending_with_a_timer_running_asks(cookbook: Scenario) -> None:
    await to_step_five(cookbook)
    await cookbook.tap("Erin", "Timer 2 min (2-3)")
    await cookbook.tap("Erin", "All done")
    assert cookbook.inbox("Erin")[-1] == "There's a timer still running. Keep it going?"
    await cookbook.tap("Erin", "Cancel them")
    assert card(cookbook) == "Timers cancelled."
