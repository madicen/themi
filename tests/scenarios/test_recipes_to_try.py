"""F49h (Michael's idea #224): recipes they want to try, kept in their own Google Doc,
"Recipes to try", read like the cookbook. Found, shown and cooked like any recipe, labelled
"to try", and not counted as the cookbook's. F49i: a keeper moves into the cookbook. The
clock starts Wednesday 21 October 2026, 9 am."""

from __future__ import annotations

import httpx
import pytest

from tests.fakes.gdocs_api import FakeGdocs
from tests.fixtures.cookbook import COOKBOOK_ID, recipe
from tests.fixtures.web import sign_in
from tests.scenarios.harness import Scenario
from tests.scenarios.test_cookbook import account_id, choose
from tests.scenarios.test_cookbook import linked as linked  # a fixture
from tests.scenarios.test_cookbook_save import URL, show
from tests.scenarios.test_triage import ERIN
from themi.ai.types import ToolResult
from themi.core import keys
from themi_home.cooking_wrap import KEEP_TEXT
from themi_home.recipes import NO_TRY_DOC_TEXT, Recipe, Recipes

TRY_ID = "1TryDocForRecipesWeWantToTryXyz"
TRY_LINK = f"https://docs.google.com/document/d/{TRY_ID}/edit"
SNOWY = recipe(
    "Snowy Earthquake Cookie",
    ["¾ (150g) Cup sugar", "⅓ (70g) Cup canola oil", "1 Cup powdered sugar"],
    ["Mix everything.", "Bake at 350°F for 12 minutes."],
)
PANCAKES_TOO = recipe("Pancakes", ["1 cup flour", "1 cup oat milk"], ["Mix.", "Fry."])


def recipes(scenario: Scenario) -> Recipes:
    found = scenario.app.services.maybe(keys.recipes)
    assert found is not None
    return found


async def choose_try(
    scenario: Scenario, site: httpx.AsyncClient, doc: str = TRY_LINK
) -> httpx.Response:
    csrf = await sign_in(scenario, site, "Erin")
    response = await site.post(
        f"/accounts/{account_id(scenario)}/cookbook",
        data={"csrf": csrf, "doc": doc, "book": "to_try"},
    )
    assert response.status_code == 303
    return await site.get(response.headers["location"])


@pytest.fixture
async def both(scenario: Scenario, linked: FakeGdocs, site: httpx.AsyncClient) -> FakeGdocs:
    """The cookbook chosen, and Recipes to try beside it (shared through Erin's account)."""
    await choose(scenario, site)
    linked.add_doc(
        TRY_ID, "Recipes to try", [("T", "Recipes to try"), *SNOWY, *PANCAKES_TOO],
        shared_with=[ERIN],
    )  # fmt: skip
    await choose_try(scenario, site)
    return linked


async def test_the_try_doc_is_chosen_and_read(
    scenario: Scenario, both: FakeGdocs, site: httpx.AsyncClient
) -> None:
    assert scenario.inbox("Erin")[-1] == "I've read 2 recipes from Recipes to try."
    trying = [r for r in recipes(scenario).all() if r.to_try]
    assert [r.name for r in trying] == ["Snowy Earthquake Cookie", "Pancakes"]
    assert all(r.key.startswith("try:") for r in trying)
    assert recipes(scenario).settings("to_try")["doc_id"] == TRY_ID
    assert recipes(scenario).doc_id == COOKBOOK_ID  # the cookbook is as it was
    page = (await site.get(f"/accounts/{account_id(scenario)}/cookbook")).text
    assert "Recipes to try: <strong>Recipes to try</strong>" in page


async def test_the_cookbooks_count_leaves_them_out(scenario: Scenario, both: FakeGdocs) -> None:
    items = [i.summary for i in recipes(scenario).open_items(scenario.member("Erin"))]
    assert items[0] == "The family cookbook has 16 recipes and charts (find_recipe)."
    assert items[1].startswith("Recipes to try (a separate doc, not the cookbook) has 2")


async def test_one_is_found_shown_and_labelled_to_try(scenario: Scenario, both: FakeGdocs) -> None:
    scenario.primary.queue_tool_call(
        "find_recipe", {"query": "snowy earthquake", "section": "", "book": ""}
    )
    (card,) = await scenario.say("Erin", "Pull up the snowy earthquake cookies")
    assert card.startswith("Snowy Earthquake Cookie (to try)\n")
    assert f"In Recipes to try: https://docs.google.com/document/d/{TRY_ID}/edit" in card
    assert "Cook this" in scenario.last_buttons("Erin")


async def test_the_cookbook_comes_first_for_the_same_name(
    scenario: Scenario, both: FakeGdocs
) -> None:
    (first, second, *_) = recipes(scenario).find("pancakes", charts=False)
    assert (first.recipe.to_try, second.recipe.to_try) == (False, True)


async def test_two_matches_say_which_docs(scenario: Scenario, both: FakeGdocs) -> None:
    scenario.primary.queue_tool_call(
        "find_recipe", {"query": "pancakes", "section": "", "book": ""}
    )
    replies = await scenario.say("Erin", "What's the pancake recipe?")
    assert replies == ["From the cookbook and Recipes to try:"]
    assert scenario.last_buttons("Erin")[:2] == ["Pancakes", "Pancakes (to try)"]


async def test_the_recipes_page_has_them_under_their_own_heading(
    scenario: Scenario, both: FakeGdocs, site: httpx.AsyncClient
) -> None:
    page = (await site.get("/recipes")).text
    heading = page.index("<h2>To try</h2>")
    assert page.index("Snowy Earthquake Cookie") > heading
    assert page.index("Alfredo Sauce") < heading


async def test_the_same_doc_cant_be_both(
    scenario: Scenario, both: FakeGdocs, site: httpx.AsyncClient
) -> None:
    from tests.fixtures.cookbook import LINK

    page = await choose_try(scenario, site, LINK)
    assert "That doc is the cookbook already; pick another one." in page.text
    assert recipes(scenario).try_doc_id == TRY_ID


# ----- saving one to try ---------------------------------------------------------------------


@pytest.fixture
async def site_recipe(scenario: Scenario, both: FakeGdocs) -> FakeGdocs:
    from tests.fakes.recipe_site import FakeRecipeSite, recipe_page
    from tests.scenarios.test_cookbook_save import BROWNIES

    fake = FakeRecipeSite()
    fake.page(URL, recipe_page(BROWNIES))
    scenario.app.services.maybe(keys.web_recipes).reader = fake.reader()  # type: ignore[union-attr]
    return both


async def test_a_web_recipe_saved_to_try_goes_into_the_try_doc(
    scenario: Scenario, site_recipe: FakeGdocs
) -> None:
    await show(scenario)
    assert "Save to try" in scenario.last_buttons("Erin")
    await scenario.tap("Erin", "Save to try")
    preview, card = scenario.inbox("Erin")[-2:]
    assert preview.splitlines()[:2] == ["Here's how it would go in Recipes to try:",
                                        "> Vegan Brownies"]  # fmt: skip
    assert "Recipes to try" in card
    await scenario.tap("Erin", "Go ahead")
    assert ("Vegan Brownies", "HEADING_4") in site_recipe.paragraphs(TRY_ID)
    assert ("Vegan Brownies", "HEADING_4") not in site_recipe.paragraphs(COOKBOOK_ID)
    brownies = next(r for r in recipes(scenario).all() if r.name == "Vegan Brownies")
    assert (brownies.source, brownies.book) == ("doc", "to_try")
    assert brownies.key.startswith("try:")


async def test_save_it_to_try_in_chat(scenario: Scenario, site_recipe: FakeGdocs) -> None:
    await show(scenario)
    scenario.primary.queue_tool_call(
        "save_recipe_to_cookbook", {"recipe": "", "section": "", "where": "to_try"}
    )
    replies = await scenario.say("Erin", "Let's save that one to try")
    assert replies[0].startswith("Here's how it would go in Recipes to try:")


async def test_without_a_try_doc_it_says_where_to_choose_one(
    scenario: Scenario, linked: FakeGdocs, site: httpx.AsyncClient
) -> None:
    from tests.fakes.recipe_site import FakeRecipeSite, recipe_page
    from tests.scenarios.test_cookbook_save import BROWNIES

    await choose(scenario, site)
    fake = FakeRecipeSite()
    fake.page(URL, recipe_page(BROWNIES))
    scenario.app.services.maybe(keys.web_recipes).reader = fake.reader()  # type: ignore[union-attr]
    await show(scenario)
    assert "Save to try" not in scenario.last_buttons("Erin")
    scenario.primary.queue_tool_call(
        "save_recipe_to_cookbook", {"recipe": "", "section": "", "where": "to_try"}
    )
    scenario.primary.queue_text("There's no try doc yet.")
    await scenario.say("Erin", "Save that one to try")
    result = [
        b.content
        for m in scenario.primary.last_request.messages
        for b in m.content
        if isinstance(b, ToolResult)
    ][-1]
    assert result.startswith(NO_TRY_DOC_TEXT)


# ----- F49i: a keeper moves into the cookbook ------------------------------------------------


def cookbook_names(gdocs: FakeGdocs, doc_id: str) -> list[str]:
    return [text for text, style in gdocs.paragraphs(doc_id) if style == "HEADING_4"]


def snowy(scenario: Scenario) -> Recipe:
    return next(r for r in recipes(scenario).all() if r.name == "Snowy Earthquake Cookie")


async def move_in_chat(scenario: Scenario, name: str = "snowy earthquake") -> list[str]:
    scenario.primary.queue_tool_call(
        "save_recipe_to_cookbook", {"recipe": name, "section": "", "where": "cookbook"}
    )
    return await scenario.say("Erin", "Move the snowy earthquake cookies to the cookbook")


async def test_move_it_to_the_cookbook_in_chat(scenario: Scenario, both: FakeGdocs) -> None:
    before = snowy(scenario)
    (preview, *_) = await move_in_chat(scenario)
    assert preview.splitlines()[0] == "Here's how it would go in the cookbook, under Desserts:"
    assert "> ¾ Cup (150g) sugar" in preview  # as Themi reads it (F49c), and as it's written
    assert preview.splitlines()[-1] == "Then it comes out of Recipes to try."
    assert "out of Recipes to try" in scenario.inbox("Erin")[-1]  # the approval card
    await scenario.tap("Erin", "Go ahead")
    paragraphs = both.paragraphs(COOKBOOK_ID)
    assert ("¾ Cup (150g) sugar", "NORMAL_TEXT") in paragraphs
    at = paragraphs.index(("Snowy Earthquake Cookie", "HEADING_4"))
    desserts = paragraphs.index(("Desserts", "HEADING_1"))
    assert at > desserts
    assert not [p for p in paragraphs[desserts + 1 : at] if p[1] == "HEADING_1"]  # in Desserts
    assert "Snowy Earthquake Cookie" not in cookbook_names(both, TRY_ID)
    assert cookbook_names(both, TRY_ID) == ["Pancakes"]  # the other one stays
    assert [t for t, _ in both.paragraphs(TRY_ID)].count("-----") == 1
    after = snowy(scenario)
    assert after.id == before.id  # the same row: its cooking history stays with it
    assert (after.book, after.section, after.key.startswith("try:")) == ("cookbook", "Desserts",
                                                                         False)  # fmt: skip
    assert (
        "\nDone. Moved Snowy Earthquake Cookie to the cookbook under Desserts, and out of "
        "Recipes to try. https://docs.google.com/document/d/" in scenario.edits("Erin")[-1]["text"]
    )
    assert len([r for r in recipes(scenario).all() if r.name == "Snowy Earthquake Cookie"]) == 1


async def test_a_conflict_on_the_delete_is_read_again(scenario: Scenario, both: FakeGdocs) -> None:
    both.edits_before_write_to[TRY_ID] = 1  # someone types in the try doc once
    await move_in_chat(scenario)
    await scenario.tap("Erin", "Go ahead")
    assert cookbook_names(both, TRY_ID) == ["Pancakes"]
    assert "Done. Moved Snowy Earthquake Cookie" in scenario.edits("Erin")[-1]["text"]


async def test_a_try_doc_that_keeps_changing_leaves_it_in_both(
    scenario: Scenario, both: FakeGdocs
) -> None:
    both.edits_before_write_to[TRY_ID] = 2
    await move_in_chat(scenario)
    await scenario.tap("Erin", "Go ahead")
    assert "Snowy Earthquake Cookie" in cookbook_names(both, COOKBOOK_ID)
    assert "Snowy Earthquake Cookie" in cookbook_names(both, TRY_ID)
    assert "delete it there by hand" in scenario.edits("Erin")[-1]["text"]


async def test_the_one_to_try_is_moved_when_both_have_the_name(
    scenario: Scenario, both: FakeGdocs
) -> None:
    await move_in_chat(scenario, "pancakes")
    await scenario.tap("Erin", "Go ahead")
    assert cookbook_names(both, TRY_ID) == ["Snowy Earthquake Cookie"]
    assert cookbook_names(both, COOKBOOK_ID).count("Pancakes") == 2


async def test_one_in_the_cookbook_already_isnt_moved(scenario: Scenario, both: FakeGdocs) -> None:
    scenario.primary.queue_tool_call(
        "save_recipe_to_cookbook", {"recipe": "alfredo", "section": "", "where": "cookbook"}
    )
    scenario.primary.queue_text("It's in the cookbook already.")
    await scenario.say("Erin", "Move the alfredo to the cookbook")
    assert not scenario.app.db.query("SELECT id FROM pending_actions")


async def cook_and_finish(scenario: Scenario, name: str) -> int:
    from tests.unit.test_cook_screen import lines

    cooking = scenario.app.services.maybe(keys.cooking)
    assert cooking is not None
    found = next(r for r in recipes(scenario).all() if r.name == name)
    scenario.primary.queue_structured(lines([i.text for i in found.ingredients]))
    session = await cooking.start(scenario.member("Erin"), found)
    scenario.primary.queue_structured({"jobs": []})
    for action in ("next", "next", "finish"):
        state = cooking.state(scenario.member("Erin"))
        await cooking.act_from_page(scenario.member("Erin"), session.id, action, state["seq"], {})
    return session.id


async def test_the_wrap_asks_after_one_to_try(scenario: Scenario, both: FakeGdocs) -> None:
    cooking = scenario.app.services.maybe(keys.cooking)
    assert cooking is not None
    erin = scenario.member("Erin")
    session_id = await cook_and_finish(scenario, "Snowy Earthquake Cookie")
    assert cooking.state(erin)["wrap"] == {"kind": "keep", "text": KEEP_TEXT}
    seq = cooking.state(erin)["seq"]
    tapped = await cooking.act_from_page(erin, session_id, "wrap_keep", seq, {})
    assert tapped.said == "Moving it into the cookbook is in your chat to say yes to."
    assert cooking.state(erin)["wrap"] is None or cooking.state(erin)["wrap"]["kind"] != "keep"
    await scenario.tap("Erin", "Go ahead")
    assert "Snowy Earthquake Cookie" in cookbook_names(both, COOKBOOK_ID)
    assert "Snowy Earthquake Cookie" not in cookbook_names(both, TRY_ID)


async def test_the_wrap_doesnt_ask_after_a_cookbook_recipe(
    scenario: Scenario, both: FakeGdocs
) -> None:
    cooking = scenario.app.services.maybe(keys.cooking)
    assert cooking is not None
    await cook_and_finish(scenario, "Alfredo Sauce")
    wrap = cooking.state(scenario.member("Erin"))["wrap"]
    assert wrap is None or wrap["kind"] != "keep"


async def test_michael_cooks_a_keeper_and_adds_it_in_chat(
    scenario: Scenario, both: FakeGdocs
) -> None:
    """The prompt's scenario, from chat: the card after [All done] asks, [Add to the
    cookbook], [Go ahead]; it's in the cookbook's Desserts and gone from the try doc."""
    await cook_and_finish(scenario, "Snowy Earthquake Cookie")
    done = next(e["text"] for e in reversed(scenario.edits("Erin")) if "all done" in e["text"])
    assert done.endswith("A keeper? It can go into the cookbook.")
    await scenario.tap("Erin", "Add to the cookbook")
    await scenario.tap("Erin", "Go ahead")
    assert snowy(scenario).section == "Desserts"
    assert cookbook_names(both, TRY_ID) == ["Pancakes"]


async def test_not_yet_leaves_it(scenario: Scenario, both: FakeGdocs) -> None:
    await cook_and_finish(scenario, "Snowy Earthquake Cookie")
    await scenario.tap("Erin", "Not yet")
    assert "Snowy Earthquake Cookie" in cookbook_names(both, TRY_ID)
    assert not scenario.app.db.query("SELECT id FROM pending_actions")
