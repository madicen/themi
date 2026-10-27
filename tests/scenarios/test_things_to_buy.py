"""L2a, Erin's idea #6: what isn't food goes on Things to Buy, not the grocery list; where
things come from is learned from what people say and from receipts."""

from __future__ import annotations

from typing import Any

import httpx

from tests.fakes.gmail_api import FakeGmail
from tests.fixtures.web import sign_in
from tests.scenarios.harness import Scenario
from tests.scenarios.test_triage import arrive, inbox, verdict
from themi.ai.types import ToolResult
from themi.core.buying import ThingsToBuy
from themi.core.lists import NamedList

__all__ = ["inbox"]  # the fixture, shared with the triage scenarios


def buying(scenario: Scenario) -> ThingsToBuy:
    assert scenario.app.services.buying is not None
    return scenario.app.services.buying


def to_buy(scenario: Scenario) -> NamedList:
    return buying(scenario).lists.things_to_buy(scenario.member("Erin"))


def on_it(scenario: Scenario) -> list[tuple[str, bool]]:
    return [(i.name, i.done) for i in to_buy(scenario).items]


def groceries(scenario: Scenario) -> list[str]:
    assert scenario.app.services.groceries is not None
    return [i.name for i in scenario.app.services.groceries.needed()]


def tool_result(scenario: Scenario) -> str:
    return [
        block.content
        for message in scenario.primary.last_request.messages
        for block in message.content
        if isinstance(block, ToolResult)
    ][-1]


async def say(scenario: Scenario, said: str, tool: str, args: dict[str, Any]) -> list[str]:
    scenario.primary.queue_tool_call(tool, args)
    scenario.primary.queue_text("Done.")
    return await scenario.say("Erin", said)


async def body_wash(scenario: Scenario) -> None:
    await say(
        scenario,
        "We need body wash, we get it on Amazon",
        "add_to_things_to_buy",
        {"items": [{"name": "body wash", "store": "Amazon"}]},
    )


async def test_what_isnt_food_goes_on_things_to_buy(scenario: Scenario) -> None:
    await body_wash(scenario)
    assert on_it(scenario) == [("body wash", False)]  # asked for: straight on
    assert groceries(scenario) == []
    assert (buying(scenario).kind_of("Body Wash"), buying(scenario).store_of("body wash")) == (
        "other",
        "Amazon",
    )
    await say(
        scenario,
        "Light bulbs and batteries too",
        "add_to_things_to_buy",
        {"items": [{"name": "light bulbs", "store": ""}, {"name": "batteries", "store": ""}]},
    )
    await say(
        scenario,
        "Light bulbs come from Home Depot",
        "set_usual_store",
        {"item": "light bulbs", "store": "Home Depot"},
    )
    await say(scenario, "What's on things to buy?", "show_lists", {"list": "things to buy"})
    assert tool_result(scenario) == (
        "Things to Buy: Amazon: body wash; Home Depot: light bulbs; anywhere: batteries."
    )


async def test_a_settled_answer_is_remembered_and_their_words_win(scenario: Scenario) -> None:
    await body_wash(scenario)
    await say(  # the model guesses groceries: refused, it's been settled
        scenario,
        "I'm going to Safeway later",
        "add_to_grocery_list",
        {"items": ["body wash"]},
    )
    assert "went on Things to Buy before (not food)" in tool_result(scenario)
    assert groceries(scenario) == []

    await say(
        scenario,
        "Put body wash on the grocery list",
        "add_to_grocery_list",
        {"items": ["body wash"]},
    )
    assert groceries(scenario) == ["body wash"]  # her words win
    assert buying(scenario).kind_of("body wash") == "food"  # and are remembered


async def test_inferred_items_wait_and_remembered_food_stays_off(scenario: Scenario) -> None:
    await say(scenario, "Add eggs to the grocery list", "add_to_grocery_list", {"items": ["eggs"]})
    replies = await say(
        scenario,
        "We're out of a few things",
        "add_to_things_to_buy",
        {"items": [{"name": "eggs", "store": ""}]},
    )
    assert "went on the grocery list before (remembered as food)" in tool_result(scenario)
    replies = await say(
        scenario,
        "The bathroom's a mess",
        "add_to_things_to_buy",
        {"items": [{"name": "toilet cleaner", "store": ""}]},
    )
    assert replies[0] == "Toilet cleaner for Things to Buy\nGo ahead, or not now?"
    assert on_it(scenario) == []


async def test_a_receipt_ticks_off_what_it_bought(scenario: Scenario, inbox: FakeGmail) -> None:
    await say(
        scenario,
        "Add body wash and a phone charger to things to buy",
        "add_to_things_to_buy",
        {"items": [{"name": "body wash", "store": ""}, {"name": "phone charger", "store": ""}]},
    )
    (receipt,) = await arrive(
        scenario,
        inbox,
        {
            "sender": "Amazon.com <auto-confirm@amazon.com>",
            "subject": "Your Amazon.com order",
            "text": "Dove Body Wash 1 $8.99\nTotal $8.99",
        },
    )
    scenario.primary.queue_structured({"results": [verdict(receipt, "receipt", "Amazon, $8.99")]})
    scenario.primary.queue_structured(
        {
            "kind": "shopping",
            "vendor": "Amazon",
            "items": [{"name": "lavender body wash", "quantity": "1", "price_cents": 899}],
        }
    )
    await scenario.run_periodic("email.triage")
    assert on_it(scenario) == [("body wash", True), ("phone charger", False)]
    assert buying(scenario).store_of("body wash") == "Amazon"
    rows = scenario.app.db.query("SELECT 1 FROM purchases")
    assert rows == []  # not groceries: nothing for the pantry
    prompt = scenario.primary.requests[-1].prompt
    assert "Their things-to-buy names: body wash, phone charger." in prompt.split("<data")[0]


async def test_the_lists_page_edits_the_store(scenario: Scenario, site: httpx.AsyncClient) -> None:
    await body_wash(scenario)
    csrf = await sign_in(scenario, site, "Husband")
    page = (await site.get("/lists")).text
    assert 'value="Amazon"' in page
    nl = to_buy(scenario)
    item = nl.items[0]
    await site.post(f"/lists/{nl.id}/items/{item.id}/store", data={"csrf": csrf, "store": "Target"})
    assert buying(scenario).store_of("body wash") == "Target"
    await site.post(f"/lists/{nl.id}/items/{item.id}/store", data={"csrf": csrf, "store": ""})
    assert buying(scenario).store_of("body wash") is None


async def test_mentioning_something_isnt_asking_for_it(scenario: Scenario) -> None:
    """Bug #30: "I swear all our pacifiers keep disappearing??" put pacifiers straight on
    Things to Buy. The name was in what she wrote, but she hadn't asked for anything."""
    replies = await say(
        scenario,
        "I swear all our pacifiers keep disappearing??",
        "add_to_things_to_buy",
        {"items": [{"name": "pacifiers", "store": ""}]},
    )
    assert replies[0] == "Pacifiers for Things to Buy\nGo ahead, or not now?"
    assert on_it(scenario) == []
    await say(
        scenario,
        "We need more pacifiers",
        "add_to_things_to_buy",
        {"items": [{"name": "pacifiers", "store": ""}]},
    )
    assert on_it(scenario) == [("pacifiers", False)]  # asked: straight on
