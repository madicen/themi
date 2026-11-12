"""F36b (Erin's idea #185): someday and research buys on Things to Buy, for the person who
added them. The clock starts Wednesday 21 October 2026, 9 am."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import httpx

from tests.fakes.search import FakeSearch
from tests.fixtures.web import sign_in
from tests.scenarios.harness import Scenario
from tests.scenarios.test_things_to_buy import buying, say, to_buy, tool_result
from themi import clock
from themi.channels.pauses import EVERYTHING
from themi.core import keys
from themi_home.buying import SOMEDAY_KIND

DOG_BED = {"items": [{"name": "washable dog bed", "store": "", "someday": True}]}


def someday(scenario: Scenario) -> list[tuple[str, bool, str | None]]:
    rows = scenario.app.db.query(
        "SELECT i.name, i.someday, m.name AS who FROM list_items i JOIN lists l ON "
        "l.id = i.list_id LEFT JOIN members m ON m.id = i.added_by "
        "WHERE l.purpose = 'things_to_buy' AND i.done = 0 ORDER BY i.id"
    )
    return [(r["name"], bool(r["someday"]), r["who"]) for r in rows]


def nudges(scenario: Scenario, name: str) -> list[dict[str, Any]]:
    return scenario.app.db.query(
        "SELECT o.* FROM outbox o JOIN members m ON m.id = o.member_id WHERE o.kind = ? "
        "AND m.name = ? ORDER BY o.id",
        (SOMEDAY_KIND, name),
    )


async def week_later(scenario: Scenario, days: int = 7) -> None:
    await scenario.advance(hours=24 * days, minutes=5)
    await scenario.run_periodic("buying.someday")
    await scenario.app.outbox.flush()


async def delivered(scenario: Scenario) -> None:
    """A low-priority nudge waits for a good moment: let the day go on until it's sent."""
    for _ in range(36):
        if not scenario.app.db.query(
            "SELECT 1 FROM outbox WHERE kind = ? AND status = 'queued'", (SOMEDAY_KIND,)
        ):
            return
        await scenario.advance(minutes=30)


async def test_things_to_research_buy_is_someday_and_hers(scenario: Scenario) -> None:
    await say(
        scenario,
        "Things to research buy. VNS device",
        "add_to_things_to_buy",
        {"items": [{"name": "VNS device", "store": "", "someday": True}]},
    )
    await say(
        scenario,
        "we need batteries",
        "add_to_things_to_buy",
        {"items": [{"name": "batteries", "store": "", "someday": True}]},  # not their words
    )
    assert someday(scenario) == [("VNS device", True, "Erin"), ("batteries", False, "Erin")]


async def test_describe_lists_someday_items_apart_with_whose(scenario: Scenario) -> None:
    await say(scenario, "someday: washable dog bed", "add_to_things_to_buy", DOG_BED)
    await say(
        scenario,
        "we need batteries",
        "add_to_things_to_buy",
        {"items": [{"name": "batteries", "store": ""}]},
    )
    await say(scenario, "What's on things to buy?", "show_lists", {"list": "things to buy"})
    assert tool_result(scenario) == (
        "Things to Buy: anywhere: batteries. Someday (Erin's): washable dog bed."
    )


async def test_the_cart_leaves_out_someone_elses_someday_items(scenario: Scenario) -> None:
    await say(scenario, "someday: washable dog bed", "add_to_things_to_buy", DOG_BED)
    buying(scenario).remember("washable dog bed", store="Safeway")
    for_erin = buying(scenario).from_store(scenario.member("Erin"), "Safeway")
    for_husband = buying(scenario).from_store(scenario.member("Husband"), "Safeway")
    assert for_erin is not None and for_erin[1] == ["washable dog bed"]
    assert for_husband is not None and for_husband[1] == []


async def test_the_weekly_nudge_goes_to_her_only_gently(
    scenario: Scenario, fake_search: FakeSearch
) -> None:
    await say(scenario, "someday: washable dog bed", "add_to_things_to_buy", DOG_BED)
    await scenario.run_periodic("buying.someday")
    assert nudges(scenario, "Erin") == []  # not a week yet
    await week_later(scenario)
    (nudge,) = nudges(scenario, "Erin")
    assert nudge["priority"] == "low"
    assert nudge["text"] == (
        "The washable dog bed is still on your someday list, if you feel like looking into it."
    )
    assert nudges(scenario, "Husband") == []
    await scenario.run_periodic("buying.someday")
    assert len(nudges(scenario, "Erin")) == 1  # once a week at most
    await delivered(scenario)
    assert "washable dog bed" in scenario.inbox("Erin")[-1]
    assert scenario.last_buttons("Erin") == ["Look into it now", "Keep it for someday",
                                             "Not needed"]  # fmt: skip

    web = scenario.app.services.maybe(keys.web_search)
    assert web is not None
    web.backend = fake_search.client()  # type: ignore[attr-defined]
    fake_search.result(
        "washable dog bed", "Furhaven washable dog bed", "https://shop.example/furhaven",
        "Machine-washable cover, $45.",
    )  # fmt: skip
    scenario.primary.queue_tool_call("search_web", {"query": "washable dog bed"})
    scenario.primary.queue_text("A couple of options: the Furhaven one, $45.")
    replies = await scenario.tap("Erin", "Look into it now")
    assert replies == ["A couple of options: the Furhaven one, $45."]
    assert '<data source="web">' in tool_result(scenario)


async def test_the_least_recently_asked_item_comes_next(scenario: Scenario) -> None:
    await say(scenario, "someday: washable dog bed", "add_to_things_to_buy", DOG_BED)
    await say(
        scenario,
        "research buy: VNS device",
        "add_to_things_to_buy",
        {"items": [{"name": "VNS device", "store": "", "someday": True}]},
    )
    await week_later(scenario)
    await delivered(scenario)
    await scenario.tap("Erin", "Keep it for someday")
    assert scenario.edits("Erin")[-1]["text"].endswith("Kept on your someday list.")
    await week_later(scenario)
    texts = [n["text"] for n in nudges(scenario, "Erin")]
    assert len(texts) == 2 and "dog bed" in texts[0] and "VNS device" in texts[1]


async def test_none_in_burnout_mode_or_while_paused(scenario: Scenario) -> None:
    await say(scenario, "someday: washable dog bed", "add_to_things_to_buy", DOG_BED)
    erin = scenario.member("Erin")
    scenario.app.outbox.pauses.pause(erin, EVERYTHING, clock.now() + timedelta(days=30))
    await week_later(scenario)
    assert nudges(scenario, "Erin") == []
    scenario.app.outbox.pauses.resume(erin)
    burnout = scenario.app.services.maybe(keys.burnout)
    assert burnout is not None
    await burnout.start(erin)
    await week_later(scenario)
    assert nudges(scenario, "Erin") == []


async def test_not_needed_takes_it_off(scenario: Scenario) -> None:
    await say(scenario, "someday: washable dog bed", "add_to_things_to_buy", DOG_BED)
    await week_later(scenario)
    await delivered(scenario)
    await scenario.tap("Erin", "Not needed")
    assert someday(scenario) == []
    assert scenario.edits("Erin")[-1]["text"].endswith("Took it off Things to Buy.")


async def test_made_ordinary_it_drops_out_of_the_nudges(scenario: Scenario) -> None:
    await say(scenario, "someday: washable dog bed", "add_to_things_to_buy", DOG_BED)
    await say(
        scenario,
        "I'll get the Furhaven one from Amazon",
        "set_someday",
        {"item": "washable dog bed", "someday": False, "name": "Furhaven dog bed",
         "store": "Amazon"},
    )  # fmt: skip
    assert someday(scenario) == [("Furhaven dog bed", False, "Erin")]
    assert buying(scenario).store_of("Furhaven dog bed") == "Amazon"
    await week_later(scenario)
    assert nudges(scenario, "Erin") == []


async def test_the_lists_page_toggles_someday(scenario: Scenario, site: httpx.AsyncClient) -> None:
    await say(scenario, "someday: washable dog bed", "add_to_things_to_buy", DOG_BED)
    csrf = await sign_in(scenario, site, "Erin")
    page = (await site.get("/lists")).text
    assert "Someday (Erin&#39;s)" in page and "Buy as usual" in page
    nl = to_buy(scenario)
    item = nl.items[0]
    await site.post(f"/lists/{nl.id}/items/{item.id}/someday", data={"csrf": csrf, "on": "0"})
    assert someday(scenario) == [("washable dog bed", False, "Erin")]
    await site.post(f"/lists/{nl.id}/items/{item.id}/someday", data={"csrf": csrf, "on": "1"})
    assert someday(scenario) == [("washable dog bed", True, "Erin")]
