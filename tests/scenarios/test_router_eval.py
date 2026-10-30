"""P3: the offline router eval, over the eval cases with every tool the app has. Today's
word lists set the floor; a change that loses recall fails here."""

from __future__ import annotations

from tests.evals.routing import (
    KINDS,
    format_routing,
    load_routing_cases,
    route_cases,
    totals,
)
from tests.evals.scoring import Case, load_cases
from tests.fakes.cozyla import FakeCozyla
from tests.fakes.gcal_api import FakeGcal
from tests.fakes.gmail_api import FakeGmail
from tests.fakes.ourgroceries import FakeOurGroceries
from tests.fakes.travel import FakeTravel
from tests.scenarios.harness import Scenario
from themi.core.tools import GROUP_EXAMPLES, GROUPS, TOOL_GROUPS

# choose_groups: 11/12 on 2026-10-29 (P3's Notes); 21/25 once P6 added the twins cases;
# 95/109 once P7a added the routing cases (74/84 of those; paraphrases miss most).
BASELINE_RECALL = 95 / 109


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


# ----- P7a: routing cases and group examples ------------------------------------------


def _key(text: str) -> str:
    return " ".join(text.lower().split()).strip(" ?.!")


async def test_the_routing_cases_load_and_name_built_tools(
    scenario: Scenario,
    fake_gmail: FakeGmail,
    fake_gcal: FakeGcal,
    fake_cozyla: FakeCozyla,
    fake_ourgroceries: FakeOurGroceries,
    fake_travel: FakeTravel,
) -> None:
    cases = load_routing_cases()
    assert 80 <= len(cases) <= 110
    assert len({c.id for c in cases}) == len(cases)
    assert {c.category for c in cases} == set(KINDS)
    built = {s.name for s in scenario.app.services.tools.specs()}
    for c in cases:
        assert c.needs or c.needs_any, c.id
        assert set((*c.needs, *c.needs_any)) <= built, c.id
    assert all(len(c.texts) == 2 for c in cases if c.category == "follow-up")


def test_every_group_has_examples_and_cases() -> None:
    assert set(GROUP_EXAMPLES) == set(GROUPS)
    for group, examples in GROUP_EXAMPLES.items():
        assert 10 <= len(examples) <= 20, group
        assert len({_key(e) for e in examples}) == len(examples), group
    needed = {
        TOOL_GROUPS[name]
        for c in load_routing_cases()
        for name in (*c.needs, *c.needs_any)
        if name in TOOL_GROUPS
    }
    assert needed == set(GROUPS)


def test_no_example_is_also_a_case() -> None:
    cases = {_key(t) for c in load_routing_cases() for t in c.texts}
    cases |= {_key(c.message) for c in load_cases()}
    examples = {_key(e) for examples in GROUP_EXAMPLES.values() for e in examples}
    assert not examples & cases
