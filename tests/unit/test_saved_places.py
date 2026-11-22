"""F57b: places saved by name, and pinned facts that haven't come up being unpinned."""

from datetime import timedelta

import pytest

from tests.fixtures.family import SeededFamily
from themi import clock
from themi.standard.memory import UNPIN_AFTER, Memory
from themi.standard.places import Places, named_place

LOT = "200 S Pasteur Dr, Palo Alto, CA 94304"

pytestmark = pytest.mark.usefixtures("frozen_clock")


@pytest.fixture
def places(family: SeededFamily) -> Places:
    return Places(family.db)


@pytest.fixture
def memory(family: SeededFamily) -> Memory:
    return Memory(family.db)


def named(family: SeededFamily, who: str, phrase: str) -> str | None:
    member = family.erin if who == "Erin" else family.husband
    found = named_place(family.db, member, [family.erin, family.husband], phrase, "1 Home St")
    return found.address if found else None


def test_a_place_is_found_by_its_name_another_name_or_a_phrase_holding_one(
    places: Places, family: SeededFamily
) -> None:
    places.save(family.erin, "Stanford", LOT, aliases="Stanford Hospital, the hospital")
    for phrase in ("Stanford", "stanford", "Stanford's", "the Stanford lot", "the hospital"):
        assert named(family, "Erin", phrase) == LOT, phrase
    assert named(family, "Erin", "Stanford Shopping Center, 660 Stanford Ave") is None


def test_the_longest_name_wins(places: Places, family: SeededFamily) -> None:
    places.save(family.erin, "Stanford", LOT)
    places.save(family.erin, "Stanford Shopping Center", "660 Stanford Shopping Ctr")
    assert named(family, "Erin", "the stanford shopping center") == "660 Stanford Shopping Ctr"


def test_a_place_is_found_by_its_address(places: Places, family: SeededFamily) -> None:
    saved = places.save(family.erin, "Stanford", LOT, note="Visiting 6:30-8:30 pm")
    assert places.find(family.erin, f"Visitor lot, {LOT}") == saved
    assert places.find(family.erin, "200 S Pasteur Drive North") is None
    assert places.find(family.erin, "1200 S Pasteur Dr") is None


def test_a_saved_place_beats_a_fact_for_the_same_name(
    places: Places, memory: Memory, family: SeededFamily
) -> None:
    memory.remember(family.erin, "places", "Stanford visitor parking address is 1 Old Rd")
    places.save(family.erin, "Stanford visitor parking", LOT)
    assert named(family, "Erin", "Stanford visitor parking") == LOT


def test_kin_and_facts_still_work_with_no_place(memory: Memory, family: SeededFamily) -> None:
    memory.remember(family.erin, "places", "Erin's parents' address is 790 La Para Ave.")
    assert named(family, "Erin", "my parents' house") == "790 La Para Ave"


def test_a_personal_place_is_only_its_owners(places: Places, family: SeededFamily) -> None:
    places.save(family.erin, "Work", "1 Office Park", scope="member")
    assert named(family, "Erin", "work") == "1 Office Park"
    assert places.find(family.husband, "work") is None


def test_saving_a_place_with_the_same_name_updates_it(places: Places, family: SeededFamily) -> None:
    first = places.save(family.erin, "Stanford", "1 Old Rd")
    again = places.save(
        family.husband, "stanford", LOT, aliases="Stanford, Stanford Hospital", arrive_early=500
    )
    assert again.id == first.id
    assert (again.address, again.aliases, again.arrive_early) == (LOT, "Stanford Hospital", 120)
    assert len(places.visible(family.erin)) == 1
    with pytest.raises(ValueError, match="name and an address"):
        places.save(family.erin, "Stanford", "  ")


def test_a_place_mentioned_or_searched_for(places: Places, family: SeededFamily) -> None:
    saved = places.save(family.erin, "Stanford", LOT, note="Visiting hours 6:30-8:30 pm")
    assert places.mentioned(family.erin, "I want to visit Erin tomorrow at Stanford") == [saved]
    assert places.mentioned(family.erin, "what's for dinner?") == []
    assert places.search(family.erin, "visiting hours") == [saved]
    assert places.search(family.erin, "dentist") == []


# ----- pinned facts that haven't come up -------------------------------------------------


def test_a_pinned_fact_that_hasnt_come_up_in_8_weeks_is_unpinned(
    memory: Memory, family: SeededFamily
) -> None:
    fact = memory.remember(family.erin, "vet", "Luna's vet is on Tuesdays.", pinned=True)
    clock.advance(UNPIN_AFTER - timedelta(days=1))
    assert memory.unpin_idle() == 0
    clock.advance(timedelta(days=2))
    assert memory.unpin_idle() == 1
    again = memory.get(fact.id)
    assert not again.pinned and again.unpinned_at == clock.now()
    assert memory.search("vet", family.erin) == [again]  # still saved, still found


def test_one_that_matched_7_weeks_ago_stays_pinned(memory: Memory, family: SeededFamily) -> None:
    fact = memory.remember(family.erin, "vet", "Luna's vet is on Tuesdays.", pinned=True)
    clock.advance(timedelta(weeks=1))
    memory.prompt_facts(family.erin, "when is the vet?")
    clock.advance(timedelta(weeks=7, days=-1))
    assert memory.unpin_idle() == 0
    assert memory.get(fact.id).pinned


def test_being_in_every_prompt_isnt_coming_up(memory: Memory, family: SeededFamily) -> None:
    fact = memory.remember(family.erin, "vet", "Luna's vet is on Tuesdays.", pinned=True)
    for _ in range(9):
        clock.advance(timedelta(weeks=1))
        memory.prompt_facts(family.erin, "good morning")
    assert memory.unpin_idle() == 1
    assert not memory.get(fact.id).pinned


def test_pinned_again_by_hand_counts_from_then(memory: Memory, family: SeededFamily) -> None:
    fact = memory.remember(family.erin, "vet", "Luna's vet is on Tuesdays.", pinned=True)
    clock.advance(UNPIN_AFTER + timedelta(days=1))
    memory.unpin_idle()
    memory.pin(fact.id)
    assert memory.get(fact.id).unpinned_at is None
    clock.advance(UNPIN_AFTER - timedelta(days=1))
    assert memory.unpin_idle() == 0
