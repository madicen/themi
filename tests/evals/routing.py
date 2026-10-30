"""P3: an offline eval of the tool-group router. No model: for each case in cases.json, the
router picks groups from the message, and the case is scored on whether the tools it
expects were sent (recall) and how many tools went (size).

A router is anything shaped like `choose_groups`: texts in, group names out. Today's word
lists are the baseline; a candidate (embeddings, a small model) is scored the same way.
The registry comes from a built app (the scenario harness), since features register their
tools as they install. `make router-eval` prints the numbers.
"""

from __future__ import annotations

import statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from tests.evals.scoring import Case, load_cases
from themi.core.tools import TOOL_GROUPS, ToolRegistry, choose_groups

Router = Callable[[Sequence[str]], set[str]]


@dataclass(frozen=True)
class Routed:
    case: Case
    groups: frozenset[str]
    needs_group: bool  # an expected tool is outside the core
    offered: bool  # every expected tool (and one of expect_any) was sent
    tools_sent: int
    missing: tuple[str, ...]  # expected tools that weren't sent


@dataclass(frozen=True)
class Totals:
    cases: int
    needing: int  # cases needing a group beyond the core
    offered: int  # of those, the ones that got it
    tools_sent: float  # median

    @property
    def recall(self) -> float:
        return self.offered / self.needing if self.needing else 1.0


def route_case(case: Case, router: Router, registry: ToolRegistry) -> Routed:
    groups = frozenset(router([case.message]))
    sent = {spec.name for spec in registry.specs(set(groups))}
    missing = tuple(name for name in case.expect if name not in sent)
    if case.expect_any and not sent & set(case.expect_any):
        missing += case.expect_any
    wanted = (*case.expect, *case.expect_any)
    return Routed(
        case=case,
        groups=groups,
        needs_group=any(name in TOOL_GROUPS for name in wanted),
        offered=not missing,
        tools_sent=len(sent),
        missing=missing,
    )


def route_cases(
    registry: ToolRegistry, router: Router = choose_groups, cases: list[Case] | None = None
) -> list[Routed]:
    """Every case whose tools exist (as the evals skip `requires` not yet built)."""
    known = {spec.name for spec in registry.specs()}
    return [
        route_case(case, router, registry)
        for case in (load_cases() if cases is None else cases)
        if set((*case.requires, *case.expect, *case.expect_any)) <= known
    ]


def totals(routed: list[Routed]) -> Totals:
    needing = [r for r in routed if r.needs_group]
    return Totals(
        cases=len(routed),
        needing=len(needing),
        offered=sum(1 for r in needing if r.offered),
        tools_sent=statistics.median(r.tools_sent for r in routed) if routed else 0,
    )


def format_routing(routed: list[Routed]) -> str:
    lines = []
    for category in sorted({r.case.category for r in routed}):
        t = totals([r for r in routed if r.case.category == category])
        lines.append(
            f"{category:<18} recall {t.offered}/{t.needing}  tools sent {t.tools_sent:g} (median)"
        )
    t = totals(routed)
    lines.append(
        f"{'all':<18} recall {t.offered}/{t.needing} ({t.recall:.0%})  "
        f"tools sent {t.tools_sent:g} (median), {t.cases} cases"
    )
    lines += [f"  missed {r.case.id}: {', '.join(r.missing)}" for r in routed if not r.offered]
    return "\n".join(lines)
