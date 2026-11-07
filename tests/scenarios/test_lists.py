"""L1a, Erin's idea #7: lists Themi keeps on request. Household unless someone says it's
theirs; items they wrote go straight on, inferred ones wait for a yes; ticked items stay."""

from __future__ import annotations

from typing import Any

import httpx

from tests.fixtures.web import sign_in
from tests.scenarios.harness import Scenario
from themi.ai.types import ToolResult
from themi.core import keys
from themi.core.lists import Lists, NamedList


def lists(scenario: Scenario) -> Lists:
    assert scenario.app.services.maybe(keys.lists) is not None
    return scenario.app.services.get(keys.lists)


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
    replies = await scenario.say(who, said)
    scenario.primary.drop()  # an add done as asked ends the turn without it (P2b)
    return replies


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
    ticked = await site.post(
        f"/lists/{nl.id}/items/{hats.id}/tick", data={"csrf": csrf, "done": "1"}
    )
    assert ticked.headers["location"] == f"/lists?open={nl.id}#list-{nl.id}"  # W4: stays open
    await site.post(f"/lists/{nl.id}/add", data={"csrf": csrf, "item": "Swimsuits"})
    assert items(scenario, "Erin", "packing") == [
        ("sunscreen", False),
        ("hats", True),
        ("passports", False),
        ("Swimsuits", False),
    ]
    page = (await site.get(f"/lists?open={nl.id}")).text
    assert 'class="tick ticked"' in page
    assert f'id="list-{nl.id}">\n  <details open>' in page
    assert "3 to go, 1 ticked" in page

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


# F21a, Erin's reports #115-#118 (2026-11-01), with made-up items.


async def gift_list(scenario: Scenario) -> None:
    await call(
        scenario,
        "Erin",
        "Start my gift ideas list",
        "create_list",
        {"name": "Gift ideas", "personal": True},
    )


async def test_a_message_that_opens_with_the_list_name_adds_to_it(scenario: Scenario) -> None:
    await gift_list(scenario)
    replies = await call(
        scenario,
        "Erin",
        "Gift list. A wool scarf",
        "add_to_list",
        {"list": "gift ideas", "items": ["A wool scarf"]},
    )
    assert items(scenario, "Erin", "gift ideas") == [("A wool scarf", False)]  # no card
    assert replies == ['Added "A wool scarf" to Gift ideas.']
    await call(
        scenario,
        "Erin",
        "Gift ideas: board games",
        "add_to_list",
        {"list": "gift ideas", "items": ["board games"]},
    )
    assert ("board games", False) in items(scenario, "Erin", "gift ideas")


async def test_opening_with_the_list_name_still_checks_the_items(scenario: Scenario) -> None:
    await gift_list(scenario)
    replies = await call(
        scenario,
        "Erin",
        "Gift list. Something for the garden",
        "add_to_list",
        {"list": "gift ideas", "items": ["seed packets"]},  # the model's idea, not her words
    )
    assert replies[0] == "Seed packets for Gift ideas\nGo ahead, or not now?"
    assert items(scenario, "Erin", "gift ideas") == []


async def test_a_long_item_on_a_list_off_the_wall(scenario: Scenario) -> None:
    await gift_list(scenario)
    long = "A photo book of the trip, " + "with a page for every day we were away " * 7
    long = long.strip()
    assert 250 < len(long) <= 500
    replies = await call(
        scenario, "Erin", f"Gift list. {long}", "add_to_list", {"list": "gift", "items": [long]}
    )
    assert items(scenario, "Erin", "gift ideas") == [(long, False)]
    assert replies == ["Added to Gift ideas."]  # too long to read back


async def test_a_long_item_on_a_wall_list_says_why(scenario: Scenario) -> None:
    await packing_list(scenario)
    nl = named(scenario, "Erin", "packing")
    lists(scenario).db.execute("UPDATE lists SET cozyla_list_id = 'wall-1' WHERE id = ?", (nl.id,))
    long = "the big blue cooler with the broken handle, " * 3
    assert len(long.strip()) > 100
    replies = await call(
        scenario,
        "Erin",
        f"Add {long} to the packing list",
        "add_to_list",
        {"list": "packing", "items": [long]},
    )
    assert replies == [
        "That one's over 100 characters, the most a list on the wall takes, so it isn't on "
        "Packing for the trip yet."
    ]
    assert len(named(scenario, "Erin", "packing").items) == 3


async def test_the_reply_to_a_list_add_is_themis_own(scenario: Scenario) -> None:
    await gift_list(scenario)
    scenario.primary.queue_tool_call(
        "add_to_list", {"list": "gift ideas", "items": ["It's such a nice day!"]}
    )
    scenario.primary.queue_text("Added to Gift ideas. Enjoy the sun.")
    replies = await scenario.say("Erin", "Gift list. It's such a nice day!")
    assert replies == ['Added "It\'s such a nice day!" to Gift ideas.']
