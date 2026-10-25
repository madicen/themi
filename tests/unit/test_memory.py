from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from tests.fixtures.family import SeededFamily
from themi import clock
from themi.accounts import Member
from themi.core.memory import Memory, similarity, terms
from themi.storage import migrations
from themi.storage.db import Database


class FakeRulebook:
    """Records standing reminders and writes a matching rule row (context_repairs refers to it)."""

    def __init__(self, db: Database) -> None:
        self.db = db
        self.reminders: list[tuple[int, str, str]] = []

    def add_standing_reminder(self, member: Member, summary: str, text: str) -> SimpleNamespace:
        self.reminders.append((member.id, summary, text))
        rule_id = self.db.execute(
            "INSERT INTO rules (summary, text, kind, status, affects, created_at, updated_at) "
            "VALUES (?, ?, 'standing_reminder', 'locked', ?, '2026-01-01', '2026-01-01')",
            (summary, text, member.id),
        )
        return SimpleNamespace(id=rule_id)


@pytest.fixture
def rulebook(family: SeededFamily) -> FakeRulebook:
    return FakeRulebook(family.db)


@pytest.fixture
def memory(family: SeededFamily, rulebook: FakeRulebook) -> Memory:
    return Memory(family.db, rulebook)  # type: ignore[arg-type]


# ----- storing and finding ----------------------------------------------------


def test_remembering_the_same_fact_twice_keeps_one(memory: Memory, family: SeededFamily) -> None:
    first = memory.remember(family.erin, "vet", "Luna's vet is on Tuesdays.")
    again = memory.remember(family.husband, "vet", "luna's vet is on tuesdays.")
    assert first.id == again.id
    assert len(memory.visible(family.erin)) == 1


def test_personal_facts_stay_personal(memory: Memory, family: SeededFamily) -> None:
    memory.remember(family.erin, "milk", "Erin prefers oat milk.", scope="member", pinned=True)
    memory.remember(family.erin, "bins", "Bins go out Wednesday mornings.", pinned=True)
    assert [f.fact for f in memory.pinned(family.erin)] == [
        "Erin prefers oat milk.",
        "Bins go out Wednesday mornings.",
    ]
    assert [f.fact for f in memory.pinned(family.husband)] == ["Bins go out Wednesday mornings."]
    assert memory.search("what milk do we buy", family.husband, include_pinned=True) == []
    found = memory.search("what milk do we buy", family.erin, include_pinned=True)
    assert found[0].fact == "Erin prefers oat milk."


def test_search_ranks_the_relevant_fact_first(memory: Memory, family: SeededFamily) -> None:
    memory.remember(family.erin, "plumber", "The plumber is Rosa, 555-0142.")
    memory.remember(family.erin, "vet", "Luna's vet appointments are on Tuesdays.")
    memory.remember(family.erin, "vet", "The vet clinic is on Oak Street.")
    results = memory.search("when is Luna's next vet appointment?", family.erin)
    assert results[0].fact == "Luna's vet appointments are on Tuesdays."
    assert "The plumber is Rosa, 555-0142." not in [f.fact for f in results]
    assert memory.search("is it the thing again?", family.erin) == []  # only stopwords


def test_stemming_finds_related_words(memory: Memory, family: SeededFamily) -> None:
    memory.remember(family.erin, "feeders", "The feeders are refilled every Sunday.")
    assert memory.search("refilling the feeder", family.erin)


def test_prompt_facts_split_pinned_from_retrieved_and_are_stamped(
    memory: Memory, family: SeededFamily, frozen_clock: datetime
) -> None:
    pinned = memory.remember(family.erin, "bins", "Bins go out Wednesday mornings.", pinned=True)
    vet = memory.remember(family.erin, "vet", "Luna's vet is on Tuesdays.")
    other = memory.remember(family.erin, "plumber", "The plumber is Rosa.")
    system_facts, notes = memory.for_prompt(family.erin, "is the vet on bins day?")
    assert [f.id for f in system_facts] == [pinned.id]
    assert [f.id for f in notes] == [vet.id]  # pinned facts aren't repeated as notes
    assert memory.get(vet.id).last_shown_at == frozen_clock
    assert memory.get(pinned.id).last_shown_at == frozen_clock
    assert memory.get(other.id).last_shown_at is None


def test_terms_and_similarity() -> None:
    assert terms("You keep forgetting the cat's vet is on Tuesdays!") == ["cat", "vet", "tuesdays"]
    assert similarity("The vet is on Mondays.", "The vet is on Tuesdays.") < 0.6
    assert similarity("Luna's vet is on Tuesdays.", "luna vet tuesdays") == 1.0


# ----- the four repairs ---------------------------------------------------------


def test_never_stored_saves_it_pinned(memory: Memory, family: SeededFamily) -> None:
    repair = memory.repair(family.erin, "the cat's vet day", "The cat's vet is on Tuesdays.")
    assert repair.diagnosis == "never_stored"
    assert repair.fact is not None and repair.fact.pinned
    assert repair.fact.fact == "The cat's vet is on Tuesdays."
    assert repair.message.startswith("I hadn't saved that at all.")


def test_stored_but_not_retrieved_gets_pinned(memory: Memory, family: SeededFamily) -> None:
    saved = memory.remember(family.erin, "vet", "The cat's vet is on Tuesdays.")
    repair = memory.repair(family.erin, "the cat's vet day", "The cat's vet is on Tuesdays.")
    assert repair.diagnosis == "not_retrieved"
    assert repair.fact is not None and repair.fact.id == saved.id and repair.fact.pinned


def test_stored_wrong_gets_corrected(memory: Memory, family: SeededFamily) -> None:
    saved = memory.remember(family.erin, "vet", "The cat's vet is on Mondays.")
    repair = memory.repair(family.erin, "the cat's vet day", "The cat's vet is on Tuesdays.")
    assert repair.diagnosis == "stored_wrong"
    corrected = memory.get(saved.id)
    assert corrected.fact == "The cat's vet is on Tuesdays." and corrected.pinned
    assert (
        repair.message
        == "What I had saved was out of date. I've corrected it to: The cat's vet is on Tuesdays."
    )
    assert memory.search("vet mondays", family.erin, include_pinned=True)[0].id == saved.id
    assert "Mondays" not in memory.get(saved.id).fact


def test_included_but_ignored_becomes_a_standing_reminder(
    memory: Memory, family: SeededFamily, rulebook: FakeRulebook
) -> None:
    memory.remember(family.erin, "vet", "The cat's vet is on Tuesdays.", pinned=True)
    repair = memory.repair(family.erin, "the cat's vet day", "The cat's vet is on Tuesdays.")
    assert repair.diagnosis == "ignored" and repair.rule_id == 1
    assert rulebook.reminders == [
        (family.erin.id, "Keep in mind: vet", "Always keep in mind: The cat's vet is on Tuesdays.")
    ]


def test_recently_shown_counts_as_included(
    memory: Memory, family: SeededFamily, frozen_clock: datetime
) -> None:
    memory.remember(family.erin, "vet", "The cat's vet is on Tuesdays.")
    memory.for_prompt(family.erin, "vet?")  # shown to the model just now
    assert memory.repair(family.erin, "cat vet", "").diagnosis == "ignored"
    memory2_fact = memory.remember(family.erin, "plumber", "The plumber is Rosa.")
    memory.for_prompt(family.erin, "plumber?")
    clock.advance(timedelta(days=3))  # long enough ago that it wasn't "in front of" the model
    repair = memory.repair(family.erin, "the plumber's name", "")
    assert repair.diagnosis == "not_retrieved" and repair.fact.id == memory2_fact.id  # type: ignore[union-attr]


def test_repairs_are_logged(memory: Memory, family: SeededFamily) -> None:
    memory.repair(family.erin, "the cat's vet day", "The cat's vet is on Tuesdays.")
    memory.repair(family.husband, "the bins", "Bins go out Wednesday mornings.")
    (erins,) = memory.repairs(family.erin.id)
    assert erins["diagnosis"] == "never_stored" and erins["complaint"] == "the cat's vet day"
    assert erins["fix"].startswith("saved and pinned fact")
    assert len(memory.repairs()) == 2


# ----- the migration from scratch facts ------------------------------------------


def test_scratch_facts_are_migrated_into_memory() -> None:
    db = Database(":memory:")
    known = migrations.discover()
    migrations.apply(db, known[:10])  # the schema as it was before memory existed
    db.execute(
        "INSERT INTO family (id, name, timezone, created_at, updated_at) "
        "VALUES (1, 'H', 'UTC', '2026-01-01', '2026-01-01')"
    )
    db.execute(
        "INSERT INTO members (id, name, role, created_at, updated_at) "
        "VALUES (1, 'Erin', 'admin', '2026-01-01', '2026-01-01')"
    )
    db.execute(
        "INSERT INTO scratch_facts (member_id, subject, fact, created_at) "
        "VALUES (1, 'vet', 'Vet on Tuesdays.', '2026-01-02')"
    )
    migrations.apply(db, known)
    (row,) = db.query("SELECT scope, subject, fact, source, created_by FROM facts")
    assert row == {
        "scope": "family",
        "subject": "vet",
        "fact": "Vet on Tuesdays.",
        "source": "migrated",
        "created_by": 1,
    }
    assert db.one("SELECT name FROM sqlite_master WHERE name = 'scratch_facts'") is None
    assert db.query("SELECT rowid FROM facts_fts WHERE facts_fts MATCH 'tuesdays'")
