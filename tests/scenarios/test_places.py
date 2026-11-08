"""F29e: places named instead of an address ("my parent's house"), from what's remembered."""

from __future__ import annotations

from tests.scenarios.harness import Scenario
from themi import clock
from themi.localtime import to_utc_iso
from themi.standard.places import Named, named_place


def remember(scenario: Scenario, fact: str, member: str | None = None) -> None:
    member_id = scenario.member(member).id if member else None
    now = to_utc_iso(clock.now())
    scenario.app.db.execute(
        "INSERT INTO facts (scope, member_id, subject, fact, created_at, updated_at) "
        "VALUES (?, ?, 'places', ?, ?, ?)",
        ("member" if member_id else "family", member_id, fact, now, now),
    )


def named(scenario: Scenario, who: str, phrase: str) -> Named | None:
    family = scenario.app.store.list_members()
    return named_place(scenario.app.db, scenario.member(who), family, phrase, "1 Home St")


async def test_my_parents_house_is_the_remembered_address(scenario: Scenario) -> None:
    """Bug #154: fact 3 on the Pi, word for word."""
    remember(scenario, "Erin's parents' address is 790 La Para Ave, Palo Alto, CA 94306.")
    remember(scenario, "Parent's house is the location for tutoring events", "Erin")  # no address
    for phrase in ("parent's house", "my parents' house", "Parents house", "my parent’s"):  # noqa: RUF001
        assert named(scenario, "Erin", phrase) == Named(
            " ".join(phrase.split()), "790 La Para Ave, Palo Alto, CA 94306"
        ), phrase


async def test_the_in_laws_are_the_partners_parents(scenario: Scenario) -> None:
    remember(scenario, "Erin's parents' address is 790 La Para Ave, Palo Alto, CA 94306.")
    remember(scenario, "Husband's parents live at 12 Oak Rd, Fresno.")
    assert named(scenario, "Husband", "my in law's house") == Named(
        "my in law's house", "790 La Para Ave, Palo Alto, CA 94306"
    )
    assert named(scenario, "Husband", "my parents'") == Named("my parents'", "12 Oak Rd, Fresno")
    assert named(scenario, "Erin", "the in-laws") == Named("the in-laws", "12 Oak Rd, Fresno")


async def test_a_place_with_no_address_remembered_has_none(scenario: Scenario) -> None:
    remember(scenario, "Husband's parents live at 12 Oak Rd, Fresno.")
    assert named(scenario, "Erin", "my parent's house") == Named("my parent's house", None)
    assert named(scenario, "Erin", "grandma's") == Named("grandma's", None)


async def test_addresses_and_other_places_are_for_the_map(scenario: Scenario) -> None:
    assert named(scenario, "Erin", "790 La Para Ave") is None
    assert named(scenario, "Erin", "Merit Vegetarian Restaurant, San Jose") is None
    assert named(scenario, "Erin", "home") == Named("home", "1 Home St")
