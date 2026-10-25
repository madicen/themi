from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from tests.fixtures.family import SeededFamily
from themi import clock
from themi.accounts import SYSTEM
from themi.energy.matching import Matcher, recovery_factor, task_cost
from themi.energy.model import EnergyModel

PACIFIC = ZoneInfo("America/Los_Angeles")
NINE_AM = datetime(2026, 10, 21, 9, 0, tzinfo=PACIFIC)


@pytest.fixture
def model(family: SeededFamily) -> EnergyModel:
    clock.freeze(NINE_AM)
    return EnergyModel(family.store)


@pytest.fixture
def matcher(family: SeededFamily, model: EnergyModel) -> Matcher:
    return Matcher(family.store, model)


# (Erin's energy note, hand-over cost, kind, expected assignee)
TABLE = [
    pytest.param(None, 10, "text", "Erin", id="no-swap: usual owner has room"),
    pytest.param(-3, 10, "text", "Husband", id="swap: Erin drained, partner has room"),
    pytest.param(-3, 30, "text", "Erin", id="swap blocked by the hand-over cost"),
    pytest.param(-3, 10, "call", "Husband", id="calls are his anyway"),
    pytest.param(1, 10, "call", "Husband", id="a little more room isn't worth a hand-over"),
]


@pytest.mark.parametrize(("note", "handover", "kind", "expected"), TABLE)
def test_matching_table(
    family: SeededFamily,
    model: EnergyModel,
    matcher: Matcher,
    note: int | None,
    handover: float,
    kind: str,
    expected: str,
) -> None:
    family.store.update_family(SYSTEM, handover_cost=handover)
    if note is not None:
        model.record(family.erin, "text_note", note, "how the morning went")
    assignment = matcher.assign(kind, 2, family.erin)
    assert assignment.assignee.name == expected
    assert assignment.swapped == (expected != assignment.default_owner.name)


def test_the_reason_is_in_words(family: SeededFamily, model: EnergyModel, matcher: Matcher) -> None:
    model.record(family.erin, "text_note", -3, "rough morning")
    swapped = matcher.assign("text", 2, family.erin)
    assert (
        swapped.reason == "Usually Erin's (texting), but Husband seems to have more room right now."
    )
    usual = matcher.assign("call", 1, family.erin)
    assert usual.reason == "Usually Husband's (calls)."
    assert not any(ch.isdigit() for ch in swapped.reason + usual.reason)


def test_kinds_without_an_owner_go_to_the_requester(family: SeededFamily, matcher: Matcher) -> None:
    assert matcher.assign("errand", 1, family.husband).default_owner.id == family.husband.id
    assert matcher.assign("errand", 1, family.erin).default_owner.id == family.erin.id


def test_kind_costs_count(family: SeededFamily, model: EnergyModel, matcher: Matcher) -> None:
    # If texting costs Erin three times the usual, her husband takes the bigger text jobs.
    assert matcher.assign("text", 3, family.erin).assignee.id == family.erin.id
    family.store.update_settings(SYSTEM, family.erin.id, kind_costs={"text": 3.0})
    erin = family.store.get_member(family.erin.id)
    assert matcher.assign("text", 3, erin).assignee.id == family.husband.id


def test_recovery_speed_counts(family: SeededFamily) -> None:
    assert recovery_factor(6) == 1.0
    assert recovery_factor(8) > 1.0 > recovery_factor(4)
    assert recovery_factor(100) == 1.5 and recovery_factor(0) == 0.75
    erin, husband = family.erin, family.husband  # 8h and 4h half-lives
    assert task_cost(erin, "physical", 2) > task_cost(husband, "physical", 2)


def test_no_energy_read_means_no_swap(
    family: SeededFamily, model: EnergyModel, matcher: Matcher
) -> None:
    model.record(family.erin, "text_note", -3, "rough morning")
    erin = family.store.update_settings(
        SYSTEM,
        family.erin.id,
        tracking={"text_notes": False, "message_timing": False, "device_activity": False},
    )
    assignment = matcher.assign("text", 2, erin)
    assert assignment.assignee.id == erin.id
    assert "no energy read" in assignment.reason
