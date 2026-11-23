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


# ----- F58e (bug #251): a place's hours by day --------------------------------------------


def test_hours_said_as_weekdays_and_weekends_are_seven_days() -> None:
    from datetime import time

    from themi.standard.places import read_hours

    hours = read_hours("weekdays 6:30-8:30 pm, weekends 12-8:30 pm")
    assert len(hours) == 7
    assert hours[0] == (time(18, 30), time(20, 30))  # "6:30-8:30 pm" is both pm
    assert hours[6] == (time(12, 0), time(20, 30))  # "12-8:30 pm" opens at noon
    assert read_hours("Mon-Fri 9-5 pm")[0] == (time(9), time(17))  # 9 am


def test_hours_it_cant_read_are_refused() -> None:
    from themi.standard.places import read_hours

    with pytest.raises(ValueError, match="couldn't read those hours"):
        read_hours("whenever they let us in")


def test_the_place_line_gives_the_named_days_hours(places: Places, family: SeededFamily) -> None:
    from datetime import date

    from themi.standard.places import day_named, read_hours

    hours = read_hours("weekdays 6:30-8:30 pm, weekends 12-8:30 pm")
    saved = places.save(family.erin, "Stanford", LOT, hours=hours)
    sunday = date(2026, 10, 25)
    monday = day_named("I want to visit Erin at Stanford tomorrow", sunday)
    assert monday == date(2026, 10, 26)
    assert saved.line(monday) == (
        f"Place: Stanford means {LOT}. Hours: Mon-Fri 6:30-8:30 pm; Sat-Sun 12-8:30 pm. "
        "On Mon 26 Oct: 6:30-8:30 pm."
    )
    assert day_named("see you saturday", sunday) == date(2026, 10, 31)
    assert day_named("what's for dinner?", sunday) is None


def test_saving_again_without_hours_keeps_them_and_no_hours_is_as_before(
    places: Places, family: SeededFamily
) -> None:
    from themi.standard.places import read_hours

    hours = read_hours("weekdays 6:30-8:30 pm")
    places.save(family.erin, "Stanford", LOT, hours=hours)
    again = places.save(family.erin, "stanford", LOT, note="Sign in at the desk")
    assert again.hours == hours
    plain = places.save(family.erin, "Dentist", "1 Main St, Palo Alto")
    assert plain.hours == {} and "Hours" not in plain.line()


# ----- F58f (bug #253): hours in a place's note, or said as a fact ---------------------------

PI_NOTE = "Visiting hours: 6:30\u20138:30 pm weekdays and 12\u20138:30 pm weekends."
PI_FACT = "Stanford's visiting hours are 6:30\u20138:30 pm weekdays and 12\u20138:30 pm weekends."


def test_a_place_with_no_hours_set_reads_them_from_its_note(
    places: Places, family: SeededFamily
) -> None:
    from datetime import time

    saved = places.save(family.erin, "Stanford", LOT, note=PI_NOTE)  # as place 1 on the Pi
    assert family.db.scalar("SELECT hours FROM places WHERE id = ?", (saved.id,)) == ""
    assert saved.hours[0] == (time(18, 30), time(20, 30))
    assert saved.hours[6] == (time(12), time(20, 30))


def test_hours_set_for_a_place_win_over_its_note(places: Places, family: SeededFamily) -> None:
    from datetime import time

    from themi.standard.places import read_hours

    saved = places.save(family.erin, "Stanford", LOT, note=PI_NOTE, hours=read_hours("daily 9-5"))
    assert saved.hours[6] == (time(9), time(17))


def test_a_fact_with_a_saved_places_hours_sets_them(places: Places, family: SeededFamily) -> None:
    from datetime import time

    saved = places.save(family.erin, "Stanford", LOT)
    found = places.hours_from(family.erin, PI_FACT)
    assert found is not None and found.id == saved.id
    assert places.get(saved.id).hours[0] == (time(18, 30), time(20, 30))
    assert places.hours_from(family.erin, "Stanford's hours are daily 9-5") is None  # set: kept
    assert places.hours_from(family.erin, "The library's hours are daily 9-5") is None
