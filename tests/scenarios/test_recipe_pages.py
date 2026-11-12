"""RC6: the website's Recipes page (CK1: [Cook] opens the cook screen on /session). The clock
starts Wednesday 21 October 2026, 9 am."""

from __future__ import annotations

import httpx
import pytest

from tests.fixtures.cookbook import load
from tests.fixtures.web import sign_in
from tests.scenarios.harness import Scenario
from themi.core import keys
from themi_home.cooking import Cooking


@pytest.fixture
async def signed_in(scenario: Scenario, site: httpx.AsyncClient) -> str:
    load(scenario.app.services)
    return await sign_in(scenario, site, "Erin")


def recipe_id(scenario: Scenario, name: str) -> int:
    return int(scenario.app.db.scalar("SELECT id FROM recipes WHERE name = ?", (name,)))


async def test_the_list_search_and_sections(
    scenario: Scenario, site: httpx.AsyncClient, signed_in: str
) -> None:
    page = await site.get("/recipes")
    assert page.status_code == 200
    assert "Alfredo Sauce" in page.text and "Roasted Vegetables" in page.text
    assert "Need a look" in page.text and "two Ingredients headings" in page.text
    found = await site.get("/recipes", params={"q": "chickpeas"})
    assert "Chana Masala" in found.text and "Alfredo Sauce" not in found.text
    desserts = await site.get("/recipes", params={"section": "Desserts"})
    assert "Ube Gelato" in desserts.text and "Pancakes" not in desserts.text


async def test_a_recipe_scaled(scenario: Scenario, site: httpx.AsyncClient, signed_in: str) -> None:
    pancakes = recipe_id(scenario, "Pancakes")
    page = await site.get(f"/recipes/{pancakes}", params={"scale": "double"})
    assert "3 Cups (360 grams) white whole wheat flour" in page.text
    assert "A double batch of" in page.text
    assert "Pan size and times may need changing." in page.text
    asked = await site.get(f"/recipes/{pancakes}", params={"scale": "for 6"})
    assert "doesn&#39;t say how many it makes" in asked.text


async def test_add_to_grocery_list_sends_the_card(
    scenario: Scenario, site: httpx.AsyncClient, signed_in: str
) -> None:
    alfredo = recipe_id(scenario, "Alfredo Sauce")
    scenario.primary.queue_structured(
        {"lines": [{"n": n, "item": i, "quantity": "", "unit": "", "note": "", "optional": False,
                    "staple": i in ("water", "salt", "black pepper")}
                   for n, i in enumerate(["cashews", "water", "garlic", "miso", "lemon juice",
                                          "salt", "nutmeg", "onion powder", "black pepper"], 1)]}
    )  # fmt: skip
    response = await site.post(
        f"/recipes/{alfredo}/groceries", data={"csrf": signed_in, "scale": ""}
    )
    assert response.status_code == 303
    assert scenario.inbox("Erin")[-1].startswith("For Alfredo Sauce, the grocery list would get")


async def test_cook_this_opens_the_cook_screen(
    scenario: Scenario, site: httpx.AsyncClient, signed_in: str
) -> None:
    """CK1 retired RC6's kitchen view: [Cook] lands on /session, the cook screen. F41b (bug
    #198) changed what chat sees: started here, nothing reaches it (CK1 sent the card and
    every tap edited it)."""
    ranch = recipe_id(scenario, "Silken Tofu Ranch Dressing")
    items = ["silken tofu", "water", "olive oil", "garlic", "onion powder", "salt",
             "apple cider vinegar", "nutritional yeast", "fresh herbs", "peppercorns"]  # fmt: skip
    scenario.primary.queue_structured(
        {"lines": [{"n": n, "item": i, "quantity": "", "unit": "", "note": "", "optional": False,
                    "staple": False} for n, i in enumerate(items, 1)]}
    )  # fmt: skip
    cooked = await site.post(f"/recipes/{ranch}/cook", data={"csrf": signed_in, "scale": ""})
    assert cooked.headers["location"] == "/session"
    view = await site.get("/session")
    assert "cook-page" in view.text and "1 package silken tofu (12.3oz) firm" in view.text
    assert scenario.inbox("Erin") == []  # F41b: no card in chat
    session = scenario.app.services.maybe(keys.cooking).current(scenario.member("Erin"))  # type: ignore[union-attr]
    assert session is not None
    scenario.primary.queue_structured({"jobs": []})
    scenario.primary.queue_structured({"steps": []})  # CK2: which lines the step uses
    moved = await site.post(
        f"/session/cook/{session.id}/act", headers={"X-Requested-With": "fetch"},
        data={"csrf": signed_in, "action": "next", "seq": str(session.seq)},
    )  # fmt: skip
    assert moved.json()["step"]["text"].startswith("Blend ingredients together until smooth")
    assert scenario.edits("Erin") == []  # F41b: nothing to edit in chat
    assert (await site.get("/recipes/kitchen")).headers["location"] == "/session"


async def test_only_family_members(scenario: Scenario, site: httpx.AsyncClient) -> None:
    load(scenario.app.services)
    page = await site.get("/recipes", follow_redirects=False)
    assert page.status_code in (302, 303, 401)
    assert "Alfredo Sauce" not in page.text


async def test_the_diet_setting(
    scenario: Scenario, site: httpx.AsyncClient, signed_in: str
) -> None:
    await site.post("/recipes/diet", data={"csrf": signed_in})
    assert scenario.app.services.maybe(keys.recipes).diet() == ""  # type: ignore[union-attr]
    await site.post("/recipes/diet", data={"csrf": signed_in, "vegan": "on"})
    assert scenario.app.services.maybe(keys.recipes).diet() == "vegan"  # type: ignore[union-attr]


async def test_it_is_on_the_more_page(
    scenario: Scenario, site: httpx.AsyncClient, signed_in: str
) -> None:
    more = await site.get("/more")
    assert 'href="/recipes"' in more.text


# ----- F41b, bug #198: cooking started on the website stays on the screen -------------------


async def cook_on_the_site(
    scenario: Scenario, site: httpx.AsyncClient, signed_in: str
) -> tuple[Cooking, int]:
    """Pancakes from the website's Cook button, as Michael did (session 16)."""
    pancakes = recipe_id(scenario, "Pancakes")
    scenario.primary.queue_structured({"lines": []})
    cooked = await site.post(f"/recipes/{pancakes}/cook", data={"csrf": signed_in, "scale": ""})
    assert cooked.headers["location"] == "/session"
    cooking = scenario.app.services.maybe(keys.cooking)
    assert cooking is not None
    session = cooking.current(scenario.member("Erin"))
    assert session is not None and session.from_page
    return cooking, session.id


async def act(
    scenario: Scenario, site: httpx.AsyncClient, signed_in: str, cooking: Cooking, session_id: int,
    action: str, **form: str,
) -> httpx.Response:  # fmt: skip
    seq = cooking.state(scenario.member("Erin"))["seq"]
    return await site.post(
        f"/session/cook/{session_id}/act", headers={"X-Requested-With": "fetch"},
        data={"csrf": signed_in, "action": action, "seq": str(seq), **form},
    )  # fmt: skip


async def test_cook_on_the_site_sends_nothing_to_chat(
    scenario: Scenario, site: httpx.AsyncClient, signed_in: str
) -> None:
    await cook_on_the_site(scenario, site, signed_in)
    await scenario.app.outbox.flush()
    assert scenario.app.db.query("SELECT text FROM outbox WHERE kind = 'cooking'") == []
    assert scenario.inbox("Erin") == []


async def test_every_tap_on_the_screen_stays_off_chat(
    scenario: Scenario, site: httpx.AsyncClient, signed_in: str
) -> None:
    cooking, session_id = await cook_on_the_site(scenario, site, signed_in)
    scenario.primary.queue_structured({"jobs": []})
    scenario.primary.queue_structured({"steps": []})
    taps = [("next", {}), ("tick", {"n": "0"}), ("untick", {"n": "0"}), ("next", {}),
            ("skip", {}), ("goto", {"to": "3"}), ("stop", {})]  # fmt: skip
    for action, form in taps:
        await act(scenario, site, signed_in, cooking, session_id, action, **form)
    await scenario.app.outbox.flush()
    assert scenario.inbox("Erin") == []
    assert scenario.edits("Erin") == []


async def test_a_timer_set_on_the_screen_still_rings_in_telegram(
    scenario: Scenario, site: httpx.AsyncClient, signed_in: str
) -> None:
    cooking, session_id = await cook_on_the_site(scenario, site, signed_in)
    scenario.primary.queue_structured({"jobs": []})
    scenario.primary.queue_structured({"steps": []})
    for action in ("next", "next", "next"):
        await act(scenario, site, signed_in, cooking, session_id, action)
    await act(scenario, site, signed_in, cooking, session_id, "timer", minutes="1", step="1")
    await scenario.advance(minutes=1)
    await scenario.run_jobs()
    assert [t for t in scenario.inbox("Erin") if t.startswith("Time's up: ")]
    assert not [t for t in scenario.inbox("Erin") if t.startswith("Pancakes: step")]


async def test_asked_in_telegram_it_answers_there(
    scenario: Scenario, site: httpx.AsyncClient, signed_in: str
) -> None:
    cooking, session_id = await cook_on_the_site(scenario, site, signed_in)
    scenario.primary.queue_structured({"jobs": []})
    scenario.primary.queue_structured({"steps": []})
    for action in ("next", "next"):
        await act(scenario, site, signed_in, cooking, session_id, action)
    assert scenario.inbox("Erin") == []
    await scenario.say("Erin", "next")  # typed in Telegram: the card comes to chat
    assert scenario.inbox("Erin")[-1].startswith("Pancakes: step 2 of 5")
    edited = len(scenario.edits("Erin"))
    await act(scenario, site, signed_in, cooking, session_id, "next")
    assert len(scenario.edits("Erin")) == edited + 1  # from then on it's edited in place
