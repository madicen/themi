"""P3: the offline router eval, over the eval cases with every tool the app has. Today's
word lists set the floor; a change that loses recall fails here."""

from __future__ import annotations

from tests.evals.routing import format_routing, route_cases, totals
from tests.evals.scoring import Case
from tests.fakes.cozyla import FakeCozyla
from tests.fakes.gcal_api import FakeGcal
from tests.fakes.gmail_api import FakeGmail
from tests.fakes.ourgroceries import FakeOurGroceries
from tests.fakes.travel import FakeTravel
from tests.scenarios.harness import Scenario
from themi.core.tools import GROUPS, TOOL_GROUPS

# choose_groups: 11/12 on 2026-10-29 (P3's Notes); 21/25 once P6 added the twins cases, whose
# misses are "lie down", "hold the meal reminders" and "don't send me" (the settings group).
BASELINE_RECALL = 21 / 25


def case(id: str, message: str, *expect: str, any_of: tuple[str, ...] = ()) -> Case:
    return Case(id=id, category="test", message=message, expect=expect, expect_any=any_of)


CASES = [
    case("core", "Remind me to call mum", "create_task"),
    case("pantry", "What can I make for dinner?", "suggest_meals"),
    case("lists", "Add sunscreen to the packing list", "add_to_list"),
    case("either", "Out of milk", any_of=("update_pantry", "add_to_list")),
]


async def test_a_router_that_sends_everything_offers_every_case(
    scenario: Scenario,
) -> None:
    routed = route_cases(scenario.app.services.tools, lambda _: set(GROUPS), CASES)
    t = totals(routed)
    assert (t.needing, t.offered) == (3, 3)
    assert t.tools_sent == len(scenario.app.services.tools.specs())


async def test_a_router_that_misses_a_group_is_scored_down(scenario: Scenario) -> None:
    routed = route_cases(scenario.app.services.tools, lambda _: {"lists"}, CASES)
    t = totals(routed)
    assert (t.needing, t.offered) == (3, 2)  # "either" passes on the list
    missed = {r.case.id: r.missing for r in routed if not r.offered}
    assert missed == {"pantry": ("suggest_meals",)}
    assert "missed pantry: suggest_meals" in format_routing(routed)
    core_only = route_cases(scenario.app.services.tools, lambda _: set(), CASES)
    # P6: add_to_list and update_pantry are twins of the core grocery tool, so they go too.
    assert {r.case.id for r in core_only if r.offered} == {"core", "lists", "either"}
    assert all(r.tools_sent < t.tools_sent for r in core_only)


async def test_cases_for_tools_not_built_are_left_out(scenario: Scenario) -> None:
    routed = route_cases(
        scenario.app.services.tools, lambda _: set(), [case("x", "hi", "not_a_tool")]
    )
    assert routed == []


async def test_the_word_lists_keep_their_recall(
    scenario: Scenario,
    fake_gmail: FakeGmail,
    fake_gcal: FakeGcal,
    fake_cozyla: FakeCozyla,
    fake_ourgroceries: FakeOurGroceries,
    fake_travel: FakeTravel,
) -> None:
    routed = route_cases(scenario.app.services.tools)
    print("\n" + format_routing(routed))  # make router-eval shows it
    t = totals(routed)
    assert t.needing > 0 and all(name in TOOL_GROUPS for r in routed for name in r.missing)
    assert t.recall >= BASELINE_RECALL
