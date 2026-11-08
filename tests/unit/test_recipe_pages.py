"""RC4a: reading a recipe from a page someone sent, carefully."""

from __future__ import annotations

import pytest

from tests.fakes.recipe_site import FakeRecipeSite, plain_page, recipe_page
from themi_home.connectors.recipe_page import (
    Blocked,
    PageError,
    check_url,
    page_text,
    schema_recipe,
)
from themi_home.web_recipes import _plain, flags, on_page


async def resolve(host: str) -> list[str]:
    return {"inside.example": ["192.168.1.20"], "tail.example": ["100.101.102.103"]}.get(
        host, ["93.184.216.34"]
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/recipe", "http://10.0.0.5/x", "http://192.168.1.1/x",
        "http://169.254.169.254/latest", "http://100.64.0.1/x", "http://[::1]/x",
        "http://localhost:8080/", "https://themi.tail1234.ts.net/admin",
        "https://inside.example/recipe", "https://tail.example/recipe",
        "ftp://cooks.example/x", "file:///etc/passwd", "javascript:alert(1)",
    ],
)  # fmt: skip
async def test_private_and_odd_links_are_refused(url: str) -> None:
    with pytest.raises(PageError):
        await check_url(url, resolve)


async def test_a_public_link_is_fine() -> None:
    await check_url("https://cooks.example/vegan-brownies", resolve)


async def test_a_redirect_to_a_private_address_is_refused() -> None:
    site = FakeRecipeSite()
    site.page("https://cooks.example/r", status=302, location="http://192.168.1.1/admin")
    with pytest.raises(PageError, match="private address"):
        await site.reader().fetch("https://cooks.example/r")
    assert site.fetched == ["https://cooks.example/r"]  # the private one was never asked


async def test_redirects_are_followed_a_few_times() -> None:
    site = FakeRecipeSite()
    for n in range(5):
        site.page(
            f"https://cooks.example/{n}", status=301, location=f"https://cooks.example/{n + 1}"
        )
    with pytest.raises(PageError, match="kept sending"):
        await site.reader().fetch("https://cooks.example/0")
    site.page("https://cooks.example/5", "<html>ok</html>")
    fetched = await site.reader().fetch("https://cooks.example/3")
    assert fetched.url == "https://cooks.example/5"


async def test_refusals_size_and_kind() -> None:
    site = FakeRecipeSite()
    site.page("https://cooks.example/no", status=403)
    site.page("https://cooks.example/big", "x" * 2_100_000)
    site.page("https://cooks.example/pdf", "%PDF", content_type="application/pdf")
    with pytest.raises(Blocked):
        await site.reader().fetch("https://cooks.example/no")
    with pytest.raises(PageError, match="too big"):
        await site.reader().fetch("https://cooks.example/big")
    with pytest.raises(PageError, match="isn't a web page"):
        await site.reader().fetch("https://cooks.example/pdf")


def test_json_ld_shapes() -> None:
    plain = recipe_page(
        {"name": "Brownies", "recipeIngredient": ["1 cup flour", "2 eggs"],
         "recipeInstructions": ["Mix.", "Bake for 25 minutes."],
         "recipeYield": ["12", "12 brownies"], "totalTime": "PT45M"}
    )  # fmt: skip
    found = schema_recipe(plain, "https://www.cooks.example/b")
    assert found is not None
    assert (found.name, found.makes, found.minutes, found.site) == (
        "Brownies",
        12,
        45,
        "cooks.example",
    )
    assert found.steps == [("", "Mix."), ("", "Bake for 25 minutes.")]
    sections = recipe_page(
        {"name": "Pie", "recipeIngredient": ["1 crust"],
         "recipeInstructions": [
             {"@type": "HowToSection", "name": "Filling",
              "itemListElement": [{"@type": "HowToStep", "text": "Stir the <b>filling</b>."}]},
             {"@type": "HowToStep", "text": "Bake."}]},
        graph=True,
    )  # fmt: skip
    pie = schema_recipe(sections, "https://cooks.example/pie")
    assert pie is not None and pie.steps == [("Filling", "Stir the filling."), ("", "Bake.")]
    text_steps = recipe_page(
        {"name": "Tea", "recipeIngredient": ["1 tea bag"], "recipeInstructions": "Boil.\nSteep."}
    )
    assert schema_recipe(text_steps, "https://x.example/").steps == [("", "Boil."), ("", "Steep.")]  # type: ignore[union-attr]
    assert schema_recipe(plain_page("Soup", ["1 leek"], ["Cook."]), "https://x.example/") is None


def test_page_text_leaves_out_scripts() -> None:
    text = page_text(plain_page("Soup", ["1 leek"], ["Cook it."], story="My grandmother..."))
    assert "var x" not in text and "1 leek" in text and "Cook it." in text


def test_on_the_page() -> None:
    page = _plain(page_text(plain_page("Soup", ["1 ½ cups leeks, sliced"], ["Cook it."])))
    assert on_page("1 ½ cups leeks, sliced", page)
    assert not on_page("2 cups cream", page)


def test_vegan_flags_and_excuses() -> None:
    lines = [
        "2 large eggs", "½ cup butter, melted", "1 cup peanut butter", "1 cup almond milk",
        "1 tbsp cream of tartar", "2 tbsp vegan butter", "1 flax egg", "½ cup grated parmesan",
        "1 lb chicken seitan", "2 tbsp honey", "1 cup buttermilk",
    ]  # fmt: skip
    assert [(w, word) for w, word, _ in flags(lines)] == [
        ("eggs", "eggs"), ("butter", "butter"), ("cheese", "parmesan"), ("honey", "honey"),
        ("buttermilk", "buttermilk"),
    ]  # fmt: skip
    assert flags(["1 cup oat milk", "1 block tofu", "1 eggplant", "1 butternut squash"]) == []
