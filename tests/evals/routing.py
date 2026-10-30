"""P3: an offline eval of the tool-group router. No model: for each case in cases.json, the
router picks groups from the message, and the case is scored on whether the tools it
expects were sent (recall) and how many tools went (size).

A router is anything shaped like `choose_groups`: texts in, group names out. Today's word
lists are the baseline; a candidate (embeddings, a small model) is scored the same way.
The registry comes from a built app (the scenario harness), since features register their
tools as they install. `make router-eval` prints the numbers.

P7a adds `routing_cases.json`: about 90 messages (some with the message before, for
follow-ups like "and butter") and the tools they need, in four kinds: plain, paraphrase,
follow-up and two-asks. They're paraphrases of the kinds of thing the family says, with
no names, places, health or money details of theirs, and a person checked each label.
"""

from __future__ import annotations

import json
import statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from tests.evals.scoring import Case, load_cases
from themi.core.tools import TOOL_GROUPS, ToolRegistry, choose_groups

Router = Callable[[Sequence[str]], set[str]]
ROUTING_FILE = Path(__file__).parent / "routing_cases.json"
KINDS = ("plain", "paraphrase", "follow-up", "two-asks")


@dataclass(frozen=True)
class Routable:
    """One message to route: a routing case, or an eval case seen the same way."""

    id: str
    category: str  # an eval case's category, or a routing case's kind
    texts: tuple[str, ...]  # the message, then the one before it (if any)
    needs: tuple[str, ...]  # every one of these tools must be sent
    needs_any: tuple[str, ...] = ()  # and one of these
    requires: tuple[str, ...] = ()  # left out until these tools are built


def from_case(case: Case) -> Routable:
    return Routable(
        case.id, case.category, (case.message,), case.expect, case.expect_any, case.requires
    )


def load_routing_cases(path: Path = ROUTING_FILE) -> list[Routable]:
    raw = json.loads(path.read_text())["cases"]
    return [
        Routable(
            id=item["id"],
            category=item["kind"],
            texts=(item["message"], *([item["before"]] if item.get("before") else [])),
            needs=tuple(item.get("tools", [])),
            needs_any=tuple(item.get("any_of", [])),
        )
        for item in raw
    ]


@dataclass(frozen=True)
class Routed:
    case: Routable
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


def route_case(case: Case | Routable, router: Router, registry: ToolRegistry) -> Routed:
    case = from_case(case) if isinstance(case, Case) else case
    groups = frozenset(router(case.texts))
    sent = {spec.name for spec in registry.specs(set(groups))}
    missing = tuple(name for name in case.needs if name not in sent)
    if case.needs_any and not sent & set(case.needs_any):
        missing += case.needs_any
    wanted = (*case.needs, *case.needs_any)
    return Routed(
        case=case,
        groups=groups,
        needs_group=any(name in TOOL_GROUPS for name in wanted),
        offered=not missing,
        tools_sent=len(sent),
        missing=missing,
    )


def route_cases(
    registry: ToolRegistry,
    router: Router = choose_groups,
    cases: Sequence[Case | Routable] | None = None,
) -> list[Routed]:
    """Every case whose tools exist (as the evals skip `requires` not yet built): by
    default the eval cases and the routing cases (P7a)."""
    known = {spec.name for spec in registry.specs()}
    chosen = [*load_cases(), *load_routing_cases()] if cases is None else cases
    routable = [from_case(c) if isinstance(c, Case) else c for c in chosen]
    return [
        route_case(case, router, registry)
        for case in routable
        if set((*case.requires, *case.needs, *case.needs_any)) <= known
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
