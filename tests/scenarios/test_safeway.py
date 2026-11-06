"""35c: "fill the Safeway cart" goes to the Safeway helper (the Chrome extension) in the
family's browser, and what it added comes back as a message."""

from __future__ import annotations

import re

import httpx

from tests.fakes.gmail_api import FakeGmail
from tests.fakes.safeway_helper import FakeSafewayHelper
from tests.fixtures.web import flash, sign_in
from tests.scenarios.harness import Scenario
from tests.scenarios.test_things_to_buy import inbox
from tests.scenarios.test_triage import arrive, verdict
from themi.core.agent import CLAIMS_DONE
from themi.core.safeway import SafewayCart

__all__ = ["inbox"]  # the fixture, shared with the triage scenarios

CARD = "Eggs, 2 oat milk and bananas for the Safeway cart\nGo ahead, or not now?"


def safeway(scenario: Scenario) -> SafewayCart:
    assert scenario.app.services.safeway is not None
    return scenario.app.services.safeway


def on_the_list(scenario: Scenario, *names: str) -> None:
    assert scenario.app.services.groceries is not None
    scenario.app.services.groceries.add(list(names), by=scenario.member("Erin"))


async def connect(scenario: Scenario, site: httpx.AsyncClient, name: str = "Erin") -> str:
    """Connect a helper on the website; returns the token the page shows once."""
    csrf = await sign_in(scenario, site, name)
    page = await site.post("/safeway/connect", data={"csrf": csrf})
    assert page.status_code == 200
    match = re.search(r'<code class="token">(swh_[\w-]+)</code>', page.text)
    assert match, "no token shown"
    return match[1]


async def ask_for_cart(scenario: Scenario) -> list[str]:
    scenario.primary.queue_tool_call("fill_safeway_cart", {})
    scenario.primary.queue_text("Here's the cart to fill.")
    return await scenario.say("Erin", "Can you fill the Safeway cart?")


def card(scenario: Scenario) -> str:
    """The approval card as it reads after a tap: the outcome is edited into it."""
    return scenario.edits("Erin")[-1]["text"]


def jobs(scenario: Scenario) -> list[tuple[str, str]]:
    return [
        (r["status"], r["items"])
        for r in scenario.app.db.query("SELECT status, items FROM safeway_jobs ORDER BY id")
    ]


# ----- the done-when story --------------------------------------------------------------


async def test_fill_the_cart_a_yes_and_the_helper_answers(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    token = await connect(scenario, site)
    helper = FakeSafewayHelper(site, token)
    on_the_list(scenario, "eggs", "2 oat milk", "bananas")
    await ask_for_cart(scenario)
    assert CARD in scenario.inbox("Erin")
    assert (await helper.claim()).status_code == 204  # nothing before the yes

    await scenario.tap("Erin", "Go ahead")
    assert "Safeway helper fill the cart with 3 things" in card(scenario)
    response = await helper.fill({"oat milk": "out_of_stock"})
    assert response.status_code == 200
    assert helper.jobs[0]["items"] == [
        {"name": "eggs", "qty": 1, "search": "eggs", "product": None},
        {"name": "oat milk", "qty": 2, "search": "oat milk", "product": None},
        {"name": "bananas", "qty": 1, "search": "bananas", "product": None},
    ]
    assert scenario.inbox("Erin")[-1] == (
        "2 things in the Safeway cart; oat milk was out of stock. Ready when you are."
    )
    assert [s for s, _ in jobs(scenario)] == ["done"]

    # What it picked is remembered for both browsers, and goes with the next job.
    assert safeway(scenario).product("eggs").product_id == "970000000"  # type: ignore[union-attr]
    assert safeway(scenario).product("oat milk") is None  # out of stock: nothing picked
    await ask_for_cart(scenario)
    await scenario.tap("Erin", "Go ahead")
    await helper.claim()
    eggs = helper.jobs[1]["items"][0]
    assert eggs["product"] == {"id": "970000000", "name": "Eggs - 1 Each", "size": "1 Each"}


async def test_a_reply_saying_the_cart_is_filled_before_the_yes_is_replaced(
    scenario: Scenario,
) -> None:
    """2026-10-31: after "fill the safeway cart" the reply said "Safeway cart filled with the
    11 items from the grocery list", before anyone had said yes."""
    on_the_list(scenario, "eggs", "2 oat milk", "bananas")
    scenario.primary.queue_tool_call("fill_safeway_cart", {})
    scenario.primary.queue_text(
        "Safeway cart filled with the 11 items from the grocery list. Ready for your review "
        "in the browser."
    )
    replies = await scenario.say("Erin", "fill the safeway cart")
    # F29d: the card is the whole answer, so the claim isn't sent at all
    assert replies[-1] == (
        "Eggs, 2 oat milk and bananas for the Safeway cart\nGo ahead, or not now?"
    )
    for claim in ("I've filled the Safeway cart.", "The cart is now filled.", "Filled the cart!"):
        assert CLAIMS_DONE.search(claim), claim


async def test_one_cart_at_a_time_and_nothing_for_an_empty_list(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    await connect(scenario, site)
    await ask_for_cart(scenario)
    assert "grocery list is empty" in str(scenario.primary.last_request.messages[-1])
    on_the_list(scenario, "eggs")
    await ask_for_cart(scenario)
    await scenario.tap("Erin", "Go ahead")
    await ask_for_cart(scenario)
    assert len(jobs(scenario)) == 1
    assert "already waiting for the helper" in str(scenario.primary.last_request.messages[-1])


# ----- the links fallback ----------------------------------------------------------------


async def test_no_helper_sends_the_list_with_links(scenario: Scenario) -> None:
    on_the_list(scenario, "eggs", "2 oat milk")
    await ask_for_cart(scenario)
    await scenario.tap("Erin", "Go ahead")
    assert "isn't connected, so here's the list with links" in card(scenario)
    assert "- oat milk (2): https://www.safeway.com/shop/search-results.html?q=oat%20milk" in card(
        scenario
    )
    assert jobs(scenario) == []


async def test_an_unclaimed_job_expires_into_links_once(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    token = await connect(scenario, site)
    on_the_list(scenario, "eggs")
    await ask_for_cart(scenario)
    await scenario.tap("Erin", "Go ahead")
    await scenario.advance(hours=1, minutes=55)
    await scenario.run_periodic("safeway.expire")
    assert [s for s, _ in jobs(scenario)] == ["queued"]
    await scenario.advance(minutes=5)
    before = len(scenario.inbox("Erin"))
    await scenario.run_periodic("safeway.expire")
    assert scenario.inbox("Erin")[before:] == [
        "The Safeway helper didn't pick up the cart, so here's the list with Safeway links "
        "instead.\n- eggs: https://www.safeway.com/shop/search-results.html?q=eggs"
    ]
    await scenario.run_periodic("safeway.expire")
    assert len(scenario.inbox("Erin")) == before + 1  # once
    helper = FakeSafewayHelper(site, token)
    assert (await helper.claim()).status_code == 204  # expired: not claimable


async def test_a_claimed_job_never_answered_expires_too(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    helper = FakeSafewayHelper(site, await connect(scenario, site))
    on_the_list(scenario, "eggs")
    await ask_for_cart(scenario)
    await scenario.tap("Erin", "Go ahead")
    await helper.claim()
    await scenario.advance(minutes=31)
    await scenario.run_periodic("safeway.expire")
    assert scenario.inbox("Erin")[-1].startswith("The Safeway helper didn't finish the cart")
    late = await helper.answer(helper.jobs[0]["id"], {"items": []})
    assert late.status_code == 422


# ----- pairing and the API --------------------------------------------------------------


async def test_a_wrong_or_revoked_token_is_refused(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    token = await connect(scenario, site)
    assert token not in str(scenario.app.db.query("SELECT * FROM safeway_helpers"))  # hashed
    assert (await FakeSafewayHelper(site, "swh_wrong").claim()).status_code == 401
    assert (await site.post("/api/safeway/claim")).status_code == 401
    assert (await site.get("/api/safeway/products")).status_code == 401
    helper = FakeSafewayHelper(site, token)
    assert (await helper.claim()).status_code == 204

    page = (await site.get("/safeway")).text
    assert "Connected by Erin" in page and token not in page  # shown only once
    csrf = re.search(r'name="csrf" value="([^"]+)"', page)[1]  # type: ignore[index]
    (helper_id,) = [h.id for h in safeway(scenario).helpers()]
    await site.post(f"/safeway/helpers/{helper_id}/revoke", data={"csrf": csrf})
    assert "Its token no longer works" in await flash(site, "/safeway")
    assert (await helper.claim()).status_code == 401


async def test_bad_answers_are_refused_and_change_nothing(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    helper = FakeSafewayHelper(site, await connect(scenario, site))
    other = FakeSafewayHelper(site, await connect(scenario, site, "Husband"))
    on_the_list(scenario, "eggs")
    await ask_for_cart(scenario)
    await scenario.tap("Erin", "Go ahead")
    await helper.claim()
    job_id = helper.jobs[0]["id"]
    assert (await helper.answer(job_id + 1, {"items": []})).status_code == 422  # unknown job
    assert (await other.answer(job_id, {"items": []})).status_code == 422  # someone else's
    bad = {"items": [{"name": "caviar", "status": "added", "qty": 1, "product": None}]}
    assert (await helper.answer(job_id, bad)).status_code == 422
    long = {
        "items": [{"name": "eggs", "status": "added", "qty": 1, "product": None}],
        "x": "y" * 70000,
    }
    assert (await helper.answer(job_id, long)).status_code == 422
    raw = await site.post(
        f"/api/safeway/jobs/{job_id}/results", headers=helper.headers, content=b"not json"
    )
    assert raw.status_code == 422
    assert [s for s, _ in jobs(scenario)] == ["claimed"]
    good = {"items": [{"name": "eggs", "status": "added", "qty": 1, "product": None}]}
    assert (await helper.answer(job_id, good)).status_code == 200
    assert (await helper.answer(job_id, good)).status_code == 422  # answered once


# ----- remembered products ---------------------------------------------------------------


async def test_products_are_listed_changed_and_forgotten_on_the_website(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    helper = FakeSafewayHelper(site, await connect(scenario, site))
    product = {"id": "960304348", "name": "Lucerne <b>Eggs</b> - 18 Count", "size": "18 Count"}
    put = await site.put(
        "/api/safeway/products", headers=helper.headers, json={"name": "eggs", "product": product}
    )
    assert put.status_code == 200
    listed = (await site.get("/api/safeway/products", headers=helper.headers)).json()
    assert listed == {"products": [{"name": "eggs", "search": None, "product": product}]}
    bad = await site.put(
        "/api/safeway/products",
        headers=helper.headers,
        json={"name": "eggs", "product": {**product, "id": "abc"}},
    )
    assert bad.status_code == 422

    page = (await site.get("/safeway")).text
    assert "Lucerne &lt;b&gt;Eggs&lt;/b&gt; - 18 Count" in page  # escaped
    csrf = re.search(r'name="csrf" value="([^"]+)"', page)[1]  # type: ignore[index]
    await site.post(
        "/safeway/products/search", data={"csrf": csrf, "name": "eggs", "words": "brown eggs"}
    )
    assert "searches for “brown eggs”" in await flash(site, "/safeway")
    eggs = safeway(scenario).product("eggs")
    assert eggs is not None and (eggs.search_words, eggs.product_id) == ("brown eggs", None)
    on_the_list(scenario, "eggs")
    await ask_for_cart(scenario)
    await scenario.tap("Erin", "Go ahead")
    await helper.claim()
    assert helper.jobs[0]["items"][0]["search"] == "brown eggs"

    await site.post("/safeway/products/forget", data={"csrf": csrf, "name": "eggs"})
    assert safeway(scenario).product("eggs") is None


async def test_a_safeway_receipt_teaches_search_words(scenario: Scenario, inbox: FakeGmail) -> None:
    (receipt,) = await arrive(
        scenario,
        inbox,
        {
            "sender": "Safeway <orders@safeway.com>",
            "subject": "Your Safeway order",
            "text": "Lucerne Farms Eggs Cage Free Large - 18 Count 1 $5.99\nTotal $5.99",
        },
    )
    scenario.primary.queue_structured({"results": [verdict(receipt, "receipt", "Safeway")]})
    scenario.primary.queue_structured(
        {
            "kind": "grocery",
            "vendor": "Safeway",
            "total_cents": 599,
            "items": [
                {
                    "name": "eggs",
                    "quantity": "1",
                    "price_cents": 599,
                    "as_written": "Lucerne Farms Eggs Cage Free Large - 18 Count",
                }
            ],
        }
    )
    await scenario.run_periodic("email.triage")
    eggs = safeway(scenario).product("eggs")
    assert eggs is not None
    assert eggs.search_words == "Lucerne Farms Eggs Cage Free Large - 18 Count"


# ----- things to buy (L2b) ---------------------------------------------------------------


def to_buy(scenario: Scenario, **stores: str) -> None:
    """Things to Buy, each item with the store it usually comes from ("" for none)."""
    buying = scenario.app.services.buying
    assert buying is not None
    erin = scenario.member("Erin")
    buying.lists.add(buying.lists.things_to_buy(erin), list(stores), erin)
    for name, store in stores.items():
        buying.remember(name, kind="other", store=store or None)


async def test_things_to_buy_from_safeway_go_in_the_same_cart(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    helper = FakeSafewayHelper(site, await connect(scenario, site))
    on_the_list(scenario, "eggs", "2 oat milk")
    to_buy(scenario, batteries="Safeway", **{"body wash": "Amazon", "2 sponges": "safeway.com"})
    to_buy(scenario, **{"light bulbs": ""})
    await ask_for_cart(scenario)
    assert (
        "Eggs and 2 oat milk for the Safeway cart, plus batteries and 2 sponges from Things to "
        "Buy\nGo ahead, or not now?"
    ) in scenario.inbox("Erin")

    await scenario.tap("Erin", "Go ahead")
    assert "fill the cart with 4 things" in card(scenario)
    await helper.fill({"sponges": "not_found"})
    assert [(i["name"], i["qty"]) for i in helper.jobs[0]["items"]] == [
        ("eggs", 1),
        ("oat milk", 2),
        ("batteries", 1),
        ("sponges", 2),
    ]
    assert scenario.inbox("Erin")[-1] == (
        "3 things in the Safeway cart; I couldn't find sponges. Ready when you are."
    )


async def test_safeway_things_to_buy_alone_make_a_cart_and_nothing_twice(
    scenario: Scenario,
) -> None:
    to_buy(scenario, batteries="Safeway", eggs="Safeway")
    await ask_for_cart(scenario)
    assert "Batteries and eggs from Things to Buy for the Safeway cart\nGo ahead, or not now?" in (
        scenario.inbox("Erin")
    )
    await scenario.tap("Erin", "Not now")
    on_the_list(scenario, "eggs")
    await ask_for_cart(scenario)
    assert "Eggs for the Safeway cart, plus batteries from Things to Buy\nGo ahead" in "\n".join(
        scenario.inbox("Erin")
    )


async def test_staging_a_cart_never_makes_the_things_to_buy_list(scenario: Scenario) -> None:
    on_the_list(scenario, "eggs")
    await ask_for_cart(scenario)
    assert "Eggs for the Safeway cart\nGo ahead, or not now?" in scenario.inbox("Erin")
    assert scenario.app.db.query("SELECT id FROM lists WHERE purpose = 'things_to_buy'") == []
