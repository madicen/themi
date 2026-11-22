"""F57a: a remembered fact comes up when the words differ, and on a follow-up."""

from datetime import timedelta

import pytest

from tests.fixtures.family import SeededFamily
from themi import clock
from themi.core.services import their_last
from themi.standard.memory import KEYWORDS_LIMIT, Memory, keyword_text
from themi.storage import migrations
from themi.storage.db import Database

HOURS = "Stanford's visiting hours are 6:30-8:30 pm on weekdays and 12-8:30 pm on weekends."


@pytest.fixture
def memory(family: SeededFamily) -> Memory:
    return Memory(family.db)


def test_search_words_find_a_fact_the_message_shares_no_word_with(
    memory: Memory, family: SeededFamily
) -> None:
    memory.remember(family.erin, "visiting hours", HOURS, keywords="Dad, hospital, visit")
    _pinned, notes = memory.prompt_facts(family.erin, "can we see dad tonight?")
    assert notes == [HOURS]


def test_without_search_words_it_isnt_found(memory: Memory, family: SeededFamily) -> None:
    memory.remember(family.erin, "visiting hours", HOURS)
    assert memory.prompt_facts(family.erin, "can we see dad tonight?") == ([], [])


def test_search_words_are_kept_tidy() -> None:
    assert (
        keyword_text(" Dad , HOSPITAL,, dad,  visiting   hours ") == "dad, hospital, visiting hours"
    )
    many = ", ".join(f"word{i}" for i in range(20))
    assert len(keyword_text(many).split(", ")) == KEYWORDS_LIMIT


def test_saying_a_fact_again_adds_its_new_search_words(
    memory: Memory, family: SeededFamily
) -> None:
    first = memory.remember(family.erin, "visiting hours", HOURS, keywords="hospital")
    again = memory.remember(family.husband, "visiting hours", HOURS, keywords="Dad, hospital")
    assert again.id == first.id
    assert again.keywords == "hospital, dad"


def test_a_follow_up_finds_what_the_earlier_message_was_about(
    memory: Memory, family: SeededFamily
) -> None:
    memory.remember(family.husband, "visiting hours", HOURS)
    _pinned, notes = memory.prompt_facts(
        family.husband, "what time should we leave?", ["let's go to Stanford"]
    )
    assert notes == [HOURS]


def test_the_latest_messages_matches_come_first_and_there_are_still_five(
    memory: Memory, family: SeededFamily
) -> None:
    for i in range(4):
        memory.remember(family.erin, "bins", f"Bin number {i} goes out on Wednesdays.")
    for i in range(3):
        memory.remember(family.erin, "vet", f"Luna's vet fact {i}: the vet is on Tuesdays.")
    _pinned, notes = memory.prompt_facts(family.erin, "when do the bins go out?", ["the vet"])
    assert len(notes) == 5
    assert all("Bin" in n for n in notes[:4])
    assert "vet" in notes[4]


def test_an_earlier_match_already_found_isnt_repeated(memory: Memory, family: SeededFamily) -> None:
    memory.remember(family.erin, "vet", "Luna's vet is on Tuesdays.")
    _pinned, notes = memory.prompt_facts(family.erin, "the vet", ["vet again"])
    assert notes == ["Luna's vet is on Tuesdays."]


class Logged:
    def __init__(self, direction: str, text: str) -> None:
        self.direction, self.text = direction, text


def test_only_their_own_messages_are_searched_not_themis_replies() -> None:
    history = [
        Logged("in", "first"),
        Logged("out", "Stanford's lot is on Pasteur Drive"),
        Logged("in", "second"),
        Logged("in", "third"),
        Logged("out", "reply"),
    ]
    assert their_last(history) == ["second", "third"]


@pytest.mark.usefixtures("frozen_clock")
def test_lookup_finds_pinned_and_unpinned_facts_and_stamps_them(
    memory: Memory, family: SeededFamily
) -> None:
    pinned = memory.remember(family.erin, "vet", "Luna's vet is on Tuesdays.", pinned=True)
    plain = memory.remember(family.erin, "vet", "The vet is on Pasteur Drive.")
    clock.advance(timedelta(minutes=5))
    found = memory.lookup(family.erin, "vet")
    assert {f.id for f in found} == {pinned.id, plain.id}
    assert memory.get(plain.id).last_shown_at == clock.now()


def test_lookup_never_finds_someone_elses_personal_fact(
    memory: Memory, family: SeededFamily
) -> None:
    memory.remember(family.erin, "milk", "Erin prefers oat milk.", scope="member")
    assert memory.lookup(family.husband, "milk") == []
    assert [f.fact for f in memory.lookup(family.erin, "milk")] == ["Erin prefers oat milk."]


def test_facts_saved_before_search_words_are_still_found() -> None:
    db = Database(":memory:")
    known = migrations.discover()
    migrations.apply(db, [m for m in known if m.version < 181])
    db.execute(
        "INSERT INTO members (id, name, role, created_at, updated_at) "
        "VALUES (1, 'Erin', 'admin', '2026-01-01', '2026-01-01')"
    )
    db.execute(
        "INSERT INTO facts (scope, subject, fact, created_by, created_at, updated_at) "
        "VALUES ('family', 'vet', 'Vet on Tuesdays.', 1, '2026-01-02', '2026-01-02')"
    )
    migrations.apply(db, known)
    assert db.query("SELECT rowid FROM facts_fts WHERE facts_fts MATCH 'tuesdays'")
    db.execute("UPDATE facts SET keywords = 'luna' WHERE id = 1")
    assert db.query("SELECT rowid FROM facts_fts WHERE facts_fts MATCH 'luna'")
    assert not db.query("SELECT rowid FROM facts_fts WHERE facts_fts MATCH 'cat'")
