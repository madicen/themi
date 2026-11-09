"""CK6: pantry, swaps and wrap-up on the cook screen: "might be out", the grocery add and the
pantry update staged through the tiers (nothing on the list before a yes), each offer once,
and the cleanup handoff. The clock starts Wednesday 21 October 2026, 9 am."""

from __future__ import annotations

from typing import Any

import pytest

from tests.fixtures.cookbook import load
from tests.scenarios.harness import Scenario
from tests.unit.test_cook_screen import ALFREDO, RANCH, lines
from themi.core import keys
from themi_home.cooking import Cooking


@pytest.fixture
def cooking(scenario: Scenario) -> Cooking:
    load(scenario.app.services)
    found = scenario.app.services.maybe(keys.cooking)
    assert found is not None
    return found


def pending(scenario: Scenario) -> list[dict[str, Any]]:
    return scenario.app.db.query(
        "SELECT category, status, summary FROM pending_actions WHERE status = 'pending'"
    )


async def start(scenario: Scenario, cooking: Cooking, name: str, names: list[str]) -> int:
    scenario.primary.queue_structured(lines(names))
    found = next(r for r in cooking.recipes.all() if r.name == name)
    session = await cooking.start(scenario.member("Erin"), found)
    return session.id


async def tap(cooking: Cooking, scenario: Scenario, session_id: int, action: str, **form: str):  # type: ignore[no-untyped-def]
    erin = scenario.member("Erin")
    return await cooking.act_from_page(erin, session_id, action, cooking.state(erin)["seq"], form)


async def test_might_be_out(scenario: Scenario, cooking: Cooking) -> None:
    pantry = scenario.app.services.maybe(keys.pantry)
    assert pantry is not None
    pantry.set_status("miso", "out", source="said")
    pantry.set_status("nutmeg", "low", source="predicted")
    pantry.set_status("garlic", "plenty", source="said")
    session_id = await start(scenario, cooking, "Alfredo Sauce", ALFREDO)
    await tap(cooking, scenario, session_id, "next")  # to gathering
    out = {g["item"] for g in cooking.state(scenario.member("Erin"))["gather"] if g["maybe_out"]}
    assert out == {"miso", "nutmeg"}


async def test_add_to_groceries_is_staged(scenario: Scenario, cooking: Cooking) -> None:
    pantry = scenario.app.services.maybe(keys.pantry)
    groceries = scenario.app.services.maybe(keys.groceries)
    assert pantry is not None and groceries is not None
    pantry.set_status("miso", "out", source="said")
    session_id = await start(scenario, cooking, "Alfredo Sauce", ALFREDO)
    await tap(cooking, scenario, session_id, "next")
    tapped = await tap(cooking, scenario, session_id, "out_groceries", n="3")
    assert tapped.ok and pending(scenario) == [
        {
            "category": "grocery_list_add",
            "status": "pending",
            "summary": "Miso for the grocery list",
        }
    ]
    assert not groceries.is_needed("miso")  # nothing on the list before a yes
    again = await tap(cooking, scenario, session_id, "out_groceries", n="3")
    assert again.said == "Miso is already on the grocery list." and len(pending(scenario)) == 1
    assert not await tap(cooking, scenario, session_id, "out_groceries", n="0")  # not out


async def test_ask_for_a_swap_carries_the_pantry(scenario: Scenario, cooking: Cooking) -> None:
    pantry = scenario.app.services.maybe(keys.pantry)
    assert pantry is not None
    pantry.set_status("miso", "out", source="said")
    pantry.set_status("tahini", "plenty", source="said")
    session_id = await start(scenario, cooking, "Alfredo Sauce", ALFREDO)
    await tap(cooking, scenario, session_id, "next")
    tapped = await tap(cooking, scenario, session_id, "out_swap", n="3")
    assert tapped.said == "I might be out of miso. What could I use instead in the Alfredo Sauce?"
    (item,) = cooking.open_items(scenario.member("Erin"))
    assert '<data source="pantry">' in item.summary and "tahini: plenty" in item.summary


async def finish(scenario: Scenario, cooking: Cooking, session_id: int) -> None:
    scenario.primary.queue_structured({"jobs": []})
    await tap(cooking, scenario, session_id, "next")
    await tap(cooking, scenario, session_id, "next")
    await tap(cooking, scenario, session_id, "finish")


async def test_used_up_stages_the_staple_only(scenario: Scenario, cooking: Cooking) -> None:
    erin = scenario.member("Erin")
    session_id = await start(scenario, cooking, "Silken Tofu Ranch Dressing", RANCH)
    scenario.primary.queue_structured({"jobs": []})
    await tap(cooking, scenario, session_id, "next")
    await tap(cooking, scenario, session_id, "next")
    await tap(cooking, scenario, session_id, "finish")
    wrap = cooking.state(erin)["wrap"]
    assert wrap["kind"] == "used" and wrap["text"] == "Anything used up?"
    assert "water" not in [c["name"] for c in wrap["chips"]]
    tapped = await tap(cooking, scenario, session_id, "wrap_used", name="olive oil")
    assert tapped.said.startswith("Olive oil: out.")
    pantry = scenario.app.services.maybe(keys.pantry)
    groceries = scenario.app.services.maybe(keys.groceries)
    assert pantry is not None and groceries is not None
    assert pantry.item("olive oil").status == "out"  # type: ignore[union-attr]
    assert pending(scenario) == [{"category": "grocery_list_add", "status": "pending",
                                  "summary": "Olive oil for the grocery list"}]  # fmt: skip
    assert not groceries.is_needed("olive oil")  # waits on a yes
    await tap(cooking, scenario, session_id, "wrap_used", name="garlic")
    assert len(pending(scenario)) == 1  # not a staple: out, and not offered for the list
    assert not await tap(cooking, scenario, session_id, "wrap_used", name="olive oil")  # once
    chips = cooking.state(erin)["wrap"]["chips"]
    assert [c["name"] for c in chips if c["on"]] == ["olive oil", "garlic"]
    await tap(cooking, scenario, session_id, "wrap_used_done")
    assert cooking.state(erin)["wrap"]["kind"] == "cleanup"


async def test_the_save_offer_for_a_web_recipe(scenario: Scenario, cooking: Cooking) -> None:
    erin = scenario.member("Erin")
    scenario.app.db.execute("UPDATE recipes SET source = 'web' WHERE name = 'Alfredo Sauce'")
    session_id = await start(scenario, cooking, "Alfredo Sauce", ALFREDO)
    await finish(scenario, cooking, session_id)
    assert cooking.state(erin)["wrap"] == {"kind": "save", "text": "Keep this one in the cookbook?"}
    tapped = await tap(cooking, scenario, session_id, "wrap_save")
    assert tapped.said == "The cookbook entry is in your chat to say yes to."
    assert [a["category"] for a in pending(scenario)] == ["cookbook_add"]  # RC5's, staged
    assert cooking.state(erin)["wrap"]["kind"] == "used"  # next, once


async def test_cleanup_company(scenario: Scenario, cooking: Cooking) -> None:
    erin = scenario.member("Erin")
    session_id = await start(scenario, cooking, "Alfredo Sauce", ALFREDO)
    await finish(scenario, cooking, session_id)
    await tap(cooking, scenario, session_id, "wrap_used_done")
    assert cooking.state(erin)["wrap"] == {"kind": "cleanup", "text": "Want company for cleanup?"}
    assert await tap(cooking, scenario, session_id, "wrap_cleanup")
    body_double = scenario.app.services.maybe(keys.body_double)
    assert body_double is not None
    session = body_double.current(erin)
    assert session is not None
    assert (session.mode, session.label) == ("sprint", "Clean up after Alfredo Sauce")
    assert cooking.state(erin)["active"] is False  # every offer made: /session is the sprint


async def test_not_now_and_nothing_more(scenario: Scenario, cooking: Cooking) -> None:
    erin = scenario.member("Erin")
    session_id = await start(scenario, cooking, "Alfredo Sauce", ALFREDO)
    await finish(scenario, cooking, session_id)
    sent = len(scenario.inbox("Erin"))
    await tap(cooking, scenario, session_id, "wrap_used_done")
    await tap(cooking, scenario, session_id, "wrap_cleanup_no")
    assert cooking.state(erin)["active"] is False
    seq = cooking.get(session_id).seq  # type: ignore[union-attr]
    assert not await cooking.act_from_page(erin, session_id, "wrap_cleanup", seq, {})  # once
    assert len(scenario.inbox("Erin")) == sent  # nothing said in chat about any of it


async def test_the_dishwasher_line(scenario: Scenario) -> None:
    from datetime import timedelta

    from themi import clock
    from themi.localtime import to_utc_iso
    from themi_home.dishwasher import Dishwasher

    dishwasher = Dishwasher.__new__(Dishwasher)  # its reads only: no Home Connect needed
    dishwasher.db = scenario.app.db  # type: ignore[attr-defined]
    dishwasher.store = scenario.app.store  # type: ignore[attr-defined]
    assert dishwasher.status_line() == ""  # no dishwasher linked
    device = scenario.app.store.add_device(
        scenario.member("Erin"), "home_connect", "BOSCH-1", "Dishwasher", "dishwasher"
    )
    now = clock.now()
    scenario.app.db.execute(
        "INSERT INTO appliance_cycles (device_id, started_at, ended_at) VALUES (?, ?, ?)",
        (device.id, to_utc_iso(now - timedelta(hours=3)), to_utc_iso(now - timedelta(hours=2))),
    )
    assert dishwasher.status_line() == "The dishwasher last finished at 7 am."
    scenario.app.db.execute(
        "INSERT INTO appliance_cycles (device_id, started_at) VALUES (?, ?)",
        (device.id, to_utc_iso(now - timedelta(minutes=10))),
    )
    assert dishwasher.status_line() == "The dishwasher is running now."
