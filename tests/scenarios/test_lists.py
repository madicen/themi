"""L1a, Erin's idea #7: lists Themi keeps on request. Household unless someone says it's
theirs; items they wrote go straight on, inferred ones wait for a yes; ticked items stay."""

from __future__ import annotations

from typing import Any

import httpx

from tests.fixtures.web import sign_in
from tests.scenarios.harness import Scenario
from themi.ai.types import ToolResult
from themi.core.lists import Lists, NamedList


def lists(scenario: Scenario) -> Lists:
    assert scenario.app.services.lists is not None
    return scenario.app.services.lists


def tool_result(scenario: Scenario) -> str:
    """What the last tool call told the model."""
    return [
        block.content
        for message in scenario.primary.last_request.messages
        for block in message.content
        if isinstance(block, ToolResult)
    ][-1]


def named(scenario: Scenario, who: str, name: str) -> NamedList:
    return lists(scenario).find(scenario.member(who), name)


def items(scenario: Scenario, who: str, name: str) -> list[tuple[str, bool]]:
    return [(i.name, i.done) for i in named(scenario, who, name).items]


async def call(
    scenario: Scenario, who: str, said: str, tool: str, args: dict[str, Any]
) -> list[str]:
    scenario.primary.queue_tool_call(tool, args)
    scenario.primary.queue_text("Done.")
    return await scenario.say(who, said)


async def packing_list(scenario: Scenario) -> None:
    await call(
        scenario,
        "Erin",
        "Make a packing list for the trip",
        "create_list",
        {"name": "Packing for the trip", "personal": False},
    )
    await call(
        scenario,
        "Erin",
        "Add sunscreen, hats and passports to the packing list",
        "add_to_list",
        {"list": "packing list", "items": ["sunscreen", "hats", "passports"]},
    )


async def test_a_household_list_from_chat(scenario: Scenario) -> None:
    await packing_list(scenario)
    assert items(scenario, "Erin", "packing") == [
        ("sunscreen", False),
        ("hats", False),
        ("passports", False),
    ]  # asked for in her own words: straight on, no card
    assert named(scenario, "Husband", "Packing for the trip").items  # the household's: his too
    (item,) = [
        i.summary
        for i in scenario.app.services.open_items(scenario.member("Husband"))
        if i.summary.startswith("Lists:")
    ]
    assert item == 'Lists: "Packing for the trip": 3 to go'


async def test_items_the_model_inferred_wait_for_a_yes(scenario: Scenario) -> None:
    await packing_list(scenario)
    replies = await call(
        scenario,
        "Erin",
        "We'll be at the beach most days",
        "add_to_list",
        {"list": "packing", "items": ["beach towels"]},
    )
    assert replies[0] == "Beach towels for Packing for the trip\nGo ahead, or not now?"
    assert ("beach towels", False) not in items(scenario, "Erin", "packing")


async def test_ticked_items_stay_until_cleared(scenario: Scenario) -> None:
    await packing_list(scenario)
    await call(
        scenario,
        "Husband",
        "Passports are packed",
        "tick_list_items",
        {"list": "packing", "items": ["passports"], "done": True},
    )
    assert ("passports", True) in items(scenario, "Erin", "packing")
    result = tool_result(scenario)
    assert "Now: Packing for the trip: sunscreen and hats (ticked: passports)." in result

    await call(
        scenario,
        "Erin",
        "Clear the packed things off the packing list",
        "remove_from_list",
        {"list": "packing", "items": [], "ticked": True},
    )
    assert items(scenario, "Erin", "packing") == [("sunscreen", False), ("hats", False)]
    await call(
        scenario,
        "Erin",
        "Add passports back",
        "add_to_list",
        {"list": "packing", "items": ["passports"]},
    )
    assert ("passports", False) in items(scenario, "Erin", "packing")


async def test_my_list_is_mine_only(scenario: Scenario) -> None:
    await call(
        scenario,
        "Erin",
        "Start my gift ideas list",
        "create_list",
        {"name": "Gift ideas", "personal": True},
    )
    assert named(scenario, "Erin", "gift ideas").personal
    assert lists(scenario).visible(scenario.member("Husband")) == []
    await call(
        scenario,
        "Husband",
        "Add a scarf to the gift ideas list",
        "add_to_list",
        {"list": "gift ideas", "items": ["scarf"]},
    )
    assert "There's no one list called" in tool_result(scenario)
    assert named(scenario, "Erin", "gift ideas").items == ()


async def test_names_are_checked_against_what_is_there(scenario: Scenario) -> None:
    await packing_list(scenario)
    await call(
        scenario,
        "Erin",
        "Tick off the snorkel",
        "tick_list_items",
        {"list": "packing", "items": ["snorkel"], "done": True},
    )
    assert tool_result(scenario) == (
        '"snorkel" isn\'t one item on Packing for the trip. On it: sunscreen, hats and '
        "passports. Nothing was changed."
    )
    await call(scenario, "Erin", "What's on the camping list?", "show_lists", {"list": "camping"})
    assert 'Their lists: "Packing for the trip". create_list makes one.' in (tool_result(scenario))


async def test_a_list_goes_without_asking_only_when_named(scenario: Scenario) -> None:
    await packing_list(scenario)
    replies = await call(
        scenario, "Erin", "We're back, get rid of that one", "delete_list", {"list": "packing"}
    )
    assert replies[0] == "Deleting the list Packing for the trip\nGo ahead, or not now?"
    assert lists(scenario).visible(scenario.member("Erin"))
    await call(scenario, "Erin", "Delete the packing list", "delete_list", {"list": "packing"})
    assert lists(scenario).visible(scenario.member("Erin")) == []


async def test_the_lists_page(scenario: Scenario, site: httpx.AsyncClient) -> None:
    await packing_list(scenario)
    csrf = await sign_in(scenario, site, "Husband")
    page = (await site.get("/lists")).text
    assert "Packing for the trip" in page and "sunscreen" in page

    nl = named(scenario, "Husband", "packing")
    hats = next(i for i in nl.items if i.name == "hats")
    await site.post(f"/lists/{nl.id}/items/{hats.id}/tick", data={"csrf": csrf, "done": "1"})
    await site.post(f"/lists/{nl.id}/add", data={"csrf": csrf, "item": "Swimsuits"})
    assert items(scenario, "Erin", "packing") == [
        ("sunscreen", False),
        ("hats", True),
        ("passports", False),
        ("Swimsuits", False),
    ]
    assert 'class="link ticked"' in (await site.get("/lists")).text

    await site.post(f"/lists/{nl.id}/clear", data={"csrf": csrf})
    assert ("hats", True) not in items(scenario, "Erin", "packing")

    await site.post("/lists", data={"csrf": csrf, "name": "Tools to borrow", "personal": "on"})
    tools = named(scenario, "Husband", "tools")
    assert tools.personal and tools.owner_id == scenario.member("Husband").id
    erin_csrf = await sign_in(scenario, site, "Erin")  # someone else's personal list: hidden
    assert "Tools to borrow" not in (await site.get("/lists")).text
    await site.post(f"/lists/{tools.id}/delete", data={"csrf": erin_csrf})
    assert lists(scenario).get(tools.id, scenario.member("Husband")) is not None

    await site.post(f"/lists/{nl.id}/delete", data={"csrf": erin_csrf})
    assert lists(scenario).visible(scenario.member("Erin")) == []
