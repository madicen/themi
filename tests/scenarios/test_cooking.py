"""RC3a: cooking a recipe with Themi, getting ready: what needs time first, gathering and
prep. The clock starts Wednesday 21 October 2026, 9 am."""

from __future__ import annotations

import pytest

from tests.fixtures.cookbook import load
from tests.scenarios.harness import Scenario

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
    assert card(cookbook) == "That's the prep done for Alfredo Sauce. Enjoy the cooking."


async def test_the_prep_is_read_once(cookbook: Scenario) -> None:
    cooking = cookbook.app.services.cooking
    recipes = cookbook.app.services.recipes
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
    assert cookbook.app.services.cooking.current(cookbook.member("Erin")) is None  # type: ignore[union-attr]


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
    cooking = cookbook.app.services.cooking
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
