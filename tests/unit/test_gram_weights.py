"""GW1: the weight book, read from the family's weights guide. The clock starts Wednesday
21 October 2026, 9 am."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from tests.fixtures.web import sign_in
from tests.fixtures.weights_guide import WEIGHTS_GUIDE
from tests.scenarios.harness import Scenario
from themi.core import keys
from themi.standard.guides import Guide
from themi_home.gram_weights import (
    GramWeights,
    WeightBook,
    guide_line,
    key,
    parse_line,
    read_amount,
)


def book(text: str = WEIGHTS_GUIDE, aliases: dict[str, str] | None = None) -> WeightBook:
    guide = Guide(1, "Weights of Common Ingredients", text, None, datetime(2026, 11, 1, tzinfo=UTC))
    return WeightBook.read(guide, aliases)


def test_every_line_of_the_pis_guide_is_read() -> None:
    weights = book()
    assert weights.unusable == []
    assert len(weights.entries) == 14  # 12 lines with weights, two of them with two
    assert {e.key for e in weights.entries} == {
        "flour", "sugar", "baking powder", "baking soda", "salt", "milk", "water", "yeast",
        "flax ground seed", "nutritional yeast", "onion powder", "garlic powder",
    }  # fmt: skip


def test_the_familys_format_and_plain_ones() -> None:
    sugar = parse_line("1 Cup Sugar / 1 Tbsp Sugar: Weight in Grams 200g / 12g")
    assert sugar is not None
    assert [(e.amount, e.unit, e.grams) for e in sugar] == [(1, "cup", 200), (1, "tbsp", 12)]
    yeast = parse_line("2 ¼ tsp Yeast: Weight in Grams 7g")
    assert yeast is not None and yeast[0].amount == 2.25
    plain = parse_line("1 cup almond flour = 96 g")
    assert plain is not None and (plain[0].key, plain[0].grams) == ("almond flour", 96)
    egg = parse_line("1 large egg 50g")
    assert egg is not None and (egg[0].key, egg[0].unit) == ("egg large", "each")
    clove = parse_line("1 clove garlic: 5 grams")
    assert clove is not None and (clove[0].key, clove[0].unit) == ("clove garlic", "each")


def test_a_heading_isnt_a_weight_and_an_odd_line_is_listed() -> None:
    assert parse_line("Weights of Common Ingredients") == []
    assert parse_line("") == []
    assert parse_line("1 cup flour is about a quarter pound") is None
    assert parse_line("1 can beans: 400g") is None  # a can has no weight of its own
    assert parse_line("1 Cup Sugar / 1 Tbsp Sugar: 200g") is None  # two amounts, one weight
    weights = book(WEIGHTS_GUIDE + "\n1 handful spinach = 30g")
    assert weights.unusable == ["1 handful spinach = 30g"]


def test_flour_never_matches_almond_flour() -> None:
    weights = book()
    assert weights.find("almond flour", "cup") is None
    assert weights.grams("almond flour", 1, "cup") is None
    assert weights.grams("flour", 1, "cup") == 120
    assert weights.grams("all-purpose flour", 2, "cup") == 240  # a seeded alias
    assert weights.grams("chickpea flour", 1, "cup") is None


def test_tbsp_sugar_is_its_own_12_g() -> None:
    weights = book()
    assert weights.grams("sugar", 1, "tbsp") == 12  # not 200 / 16
    assert weights.grams("granulated sugar", 2, "tbsp") == 24


def test_another_volume_unit_by_millilitres() -> None:
    weights = book()
    assert weights.grams("baking soda", 1, "tbsp") == pytest.approx(5 * 14.79 / 4.93)
    assert weights.grams("milk", 1, "tbsp") == pytest.approx(240 * 14.79 / 236.6)
    assert weights.grams("sugar", 1, "tsp") == pytest.approx(200 * 4.93 / 236.6)  # the cup
    assert weights.grams("onion powder", 1, "cup") == pytest.approx(2.5 * 236.6 / 4.93)


def test_weights_and_counts() -> None:
    weights = book(WEIGHTS_GUIDE + "\n1 large egg 50g")
    assert weights.grams("butter", 4, "oz") == pytest.approx(113.4)  # fixed factors
    assert weights.grams("large eggs", 2, "each") == 100
    assert weights.grams("large eggs", 1, "cup") is None  # a count only from a count
    assert weights.grams("eggs", 2, "each") is None  # "large" is a different key


def test_keys_keep_the_words_that_change_a_weight() -> None:
    assert key("Packed Brown Sugar") == key("brown sugar, packed".split(",")[0] + " packed")
    assert key("fresh organic basil") == key("basil")
    assert key("sifted flour") != key("flour")
    assert key("ground flaxseed") != key("ground flax seed")  # an alias joins them
    assert book().grams("ground flaxseed", 1, "tbsp") == 7


def test_aliases_stored_and_seeded() -> None:
    weights = book(aliases={key("plain flour"): "flour", key("besan"): key("chickpea flour")})
    assert weights.grams("plain flour", 1, "cup") == 120
    assert weights.grams("besan", 1, "cup") is None  # an alias of a weight not in the guide


def test_read_amount() -> None:
    found = read_amount("2 Tbsp maple syrup, divided")
    assert found is not None and (found.low, found.unit, found.name) == (2, "tbsp", "maple syrup")
    found = read_amount("3 cloves garlic, minced")
    assert found is not None and (found.unit, key(found.name)) == ("each", "clove garlic")
    assert read_amount("1 can chickpeas") is None
    assert read_amount("salt to taste") is None
    found = read_amount("1 cup of rolled oats (or quick oats)")
    assert found is not None and found.name == "rolled oats"


def test_a_new_line_in_the_familys_style() -> None:
    line = guide_line("almond flour", 1, "cup", 96)
    assert line == "1 Cup Almond Flour: Weight in Grams 96g"
    assert parse_line(line) == parse_line(line)  # and it reads back
    entries = parse_line(guide_line("tahini", 1, "tbsp", 15.5))
    assert entries is not None and (entries[0].key, entries[0].grams) == ("tahini", 15.5)


@pytest.fixture
def weights(scenario: Scenario) -> GramWeights:
    found = scenario.app.services.maybe(GramWeights)
    assert found is not None
    return found


def save_guide(scenario: Scenario, text: str = WEIGHTS_GUIDE) -> int:
    guides = scenario.app.services.maybe(keys.guides)
    assert guides is not None
    return guides.save(scenario.member("Erin"), "Weights of Common Ingredients", text,
                       personal=False).id  # fmt: skip


async def test_the_book_is_the_household_weights_guide(
    scenario: Scenario, weights: GramWeights
) -> None:
    assert weights.book().entries == []
    save_guide(scenario)
    assert weights.book().grams("flour", 1, "cup") == 120


async def test_an_edited_guide_is_read_again(scenario: Scenario, weights: GramWeights) -> None:
    guide_id = save_guide(scenario)
    assert weights.book().grams("water", 1, "tbsp") == 5
    guides = scenario.app.services.maybe(keys.guides)
    assert guides is not None
    assert guides.replace_line(
        guide_id,
        "1mL Water / 1 Tbsp Water: Weight in Grams 1g / 5g",
        "1mL Water / 1 Tbsp Water: Weight in Grams 1g / 15g",
    )
    assert weights.book().grams("water", 1, "tbsp") == 15
    assert guides.append_line(guide_id, "1 cup almond flour = 96 g")
    assert weights.book().grams("almond flour", 1, "cup") == 96


async def test_a_dropped_line_drops_its_source(scenario: Scenario, weights: GramWeights) -> None:
    guide_id = save_guide(scenario, WEIGHTS_GUIDE + "\n1 Cup Almond Flour: Weight in Grams 96g")
    weights.record("almond flour", "web", agrees=2, urls=["https://a.example", "https://b.example"])
    weights.record("teff flour", "wanted")
    weights.book()
    assert weights.meta(key("almond flour")) is not None
    guides = scenario.app.services.maybe(keys.guides)
    assert guides is not None
    guides.replace_line(guide_id, "1 Cup Almond Flour: Weight in Grams 96g", None)
    weights.book()
    assert weights.meta(key("almond flour")) is None
    assert weights.meta(key("teff flour")) is not None  # still wanted


async def test_a_stored_alias(scenario: Scenario, weights: GramWeights) -> None:
    save_guide(scenario)
    weights.add_alias("plain flour", "flour", scenario.member("Erin"))
    assert weights.book().grams("plain flour", 1, "cup") == 120


async def test_the_guides_page_says_where_weights_came_from(
    scenario: Scenario, weights: GramWeights, site: httpx.AsyncClient
) -> None:
    save_guide(scenario, WEIGHTS_GUIDE + "\n1 Cup Almond Flour: Weight in Grams 96g\n"
               "1 handful spinach = 30g")  # fmt: skip
    weights.record("almond flour", "web", agrees=2)
    await sign_in(scenario, site, "Erin")
    page = (await site.get("/guides")).text
    assert "found online, 2 sources agree" in page
    assert "Lines Themi can&#39;t use for grams" in page
    assert "1 handful spinach = 30g" in page


# ----- GW2: grams beside a recipe's amounts --------------------------------------------------


def grams(line: str, extra: str = "") -> str:
    from themi_home.gram_weights import weigh

    return weigh(line, book(WEIGHTS_GUIDE + extra)).line


def test_grams_beside_the_amount() -> None:
    assert grams("1 Cup flour") == "1 Cup (120 g) flour"
    assert grams("1½ Cups all-purpose flour, sifted") == "1½ Cups (180 g) all-purpose flour, sifted"
    assert grams("2 Tbsp sugar") == "2 Tbsp (24 g) sugar"
    assert grams("about 1 tsp salt") == "about 1 tsp (6 g) salt"


def test_rounding() -> None:
    from themi_home.gram_weights import rounded

    assert rounded(0.75) is None  # under 1 g: as written
    assert rounded(1.25) == 1 and rounded(1.3) == 1.5 and rounded(7.8) == 8
    assert rounded(12.4) == 12 and rounded(99.6) == 100
    assert rounded(212) == 210 and rounded(213) == 215
    assert grams("⅛ tsp salt") == "⅛ tsp salt"  # 0.75 g
    assert grams("½ tsp garlic powder") == "½ tsp (1.5 g) garlic powder"


def test_scaled_lines_ranges_and_two_amounts() -> None:
    from themi_home.quantities import scale_line

    assert grams(scale_line("1 Cup flour", 1.5).line) == "1½ Cups (180 g) flour"
    assert grams("2-3 cups milk") == "2-3 cups (480-720 g) milk"
    assert grams("1 Tbsp + 1 tsp baking soda") == "1 Tbsp + 1 tsp (20 g) baking soda"


def test_counts_weights_and_whats_left_as_written() -> None:
    eggs = "\n1 large egg 50g"
    assert grams("2 large eggs, beaten", eggs) == "2 large eggs (100 g), beaten"
    assert grams("3 eggs") == "3 eggs"  # no each-weight for an egg
    assert grams("8 oz pasta") == "8 oz (225 g) pasta"  # a fixed factor
    for line in ("200g tofu", "1 can chickpeas", "salt to taste", "a pinch of salt",
                 "Zest of 1 lemon"):  # fmt: skip
        assert grams(line) == line


def test_a_weight_the_line_gives_is_used() -> None:
    assert grams("1 Cup cashews, soaked (130g)") == "1 Cup (130 g) cashews, soaked"
    assert grams("1 Cup flour (125g)") == "1 Cup (125 g) flour"  # the recipe's, not the guide's


def test_whats_missing_is_named() -> None:
    from themi_home.gram_weights import weigh

    found = weigh("1 cup almond flour", book())
    assert (found.line, found.missing, found.unit) == ("1 cup almond flour", "almond flour", "cup")
    assert weigh("3 cloves garlic", book()).missing == "clove garlic"


def test_a_stated_weight() -> None:
    from themi_home.gram_weights import stated

    cashews = stated("1 Cup cashews, soaked in water for at least 10 minutes (130g)")
    assert cashews is not None and (cashews.name, cashews.amount, cashews.grams) == (
        "cashews",
        1,
        130,
    )
    flour = stated("1 ½ Cup (180 grams) white whole wheat flour")
    assert flour is not None and (flour.name, flour.amount) == ("white whole wheat flour", 1.5)
    assert stated("1 Tbsp + 1 tsp baking powder (20g)") is None  # two amounts
    assert stated("1 Cup cashews (1300g)") is None  # not a weight a cup could have
    assert stated("1 Cup cashews") is None


def test_plausible() -> None:
    from themi_home.gram_weights import plausible

    assert plausible(15, 1, "tbsp") and plausible(120, 1, "cup") and plausible(50, 1, "each")
    assert not plausible(150, 1, "tbsp") and not plausible(5, 1, "cup")
    assert not plausible(0.5, 1, "each") and not plausible(10, 1, "oz")
    assert plausible(9, 1, "cup") and plausible(26, 1, "cup")  # F65a: a cup of dill is 9 g


def test_a_light_weight_offers_no_tenfold() -> None:
    """F65a: "26 g for 1 cup seems very little. Did you mean 260?" for dill."""
    from themi_home.gram_weights import GramWeights

    assert GramWeights.check(None, 1, "cup", 26) is None  # type: ignore[arg-type]
    asked = GramWeights.check(None, 1, "cup", 3)  # type: ignore[arg-type]
    assert asked == ("3 g for 1 cup seems very little.", [3])  # 30 g isn't usual either
    asked = GramWeights.check(None, 1, "tbsp", 150)  # type: ignore[arg-type]
    assert asked is not None and asked[0].endswith("Did you mean 15?")


def test_bare_drops_the_measure_words() -> None:
    from themi_home.gram_weights import bare, key

    assert bare(key("rounded tsp onion powder")) == bare(key("onion powder"))
    assert bare(key("fresh herbs- dill")) == bare(key("fresh dill sprigs"))
    assert bare(key("ground nutmeg")) != bare(key("nutmeg"))
