"""P5: two saved eval runs side by side, and the decision rule for "every tool" routing.

    .venv/bin/python -m tests.evals.compare results/gemini-groups-....json \
        results/gemini-all-....json

Both runs are scored again with today's cases (as rescore does). Cases that passed every
run in one and failed every run in the other are listed first: those are real
differences, the rest is noise.

The rule, agreed before the runs (2026-10-29): the second run (the candidate) wins if its
pass rate is no lower than the first's, give or take one case; no case goes from always
passing to always failing; and its median time in model calls per case is at most 20%
more.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from tests.evals.rescore import load_run
from tests.evals.scoring import Outcome, per_case, summarise

SLOWER_BY_AT_MOST = 1.2


@dataclass(frozen=True)
class Arm:
    name: str
    counts: dict[str, tuple[int, int]]  # case: (passed, runs)
    passed_cases: float  # mean passes per run, in cases: comparable across repeat counts
    cases: int
    median_seconds: float
    median_calls: float
    median_tools_sent: float


def arm(name: str, outcomes: list[Outcome]) -> Arm:
    summary = summarise(outcomes)
    counts = per_case(outcomes)
    return Arm(
        name=name,
        counts=counts,
        passed_cases=sum(passed / runs for passed, runs in counts.values()),
        cases=len(counts),
        median_seconds=summary["median_seconds"],
        median_calls=summary["median_calls"],
        median_tools_sent=summary["median_tools_sent"],
    )


def flips(before: Arm, after: Arm) -> tuple[list[str], list[str]]:
    """(always passed before and always failed after, the other way round), over the
    cases both ran."""
    worse, better = [], []
    for case in sorted(before.counts.keys() & after.counts.keys()):
        (bp, br), (ap, ar) = before.counts[case], after.counts[case]
        if bp == br and ap == 0:
            worse.append(case)
        elif bp == 0 and ap == ar:
            better.append(case)
    return worse, better


def verdict(before: Arm, after: Arm) -> tuple[bool, list[str]]:
    """Whether `after` wins under the agreed rule, and why (or why not)."""
    worse, _ = flips(before, after)
    reasons = []
    if after.passed_cases < before.passed_cases - 1:
        reasons.append(
            f"passes {after.passed_cases:.1f} cases to {before.passed_cases:.1f}: "
            "more than one case lower"
        )
    if worse:
        reasons.append(f"always passed, now always fails: {', '.join(worse)}")
    if before.median_seconds and after.median_seconds > before.median_seconds * SLOWER_BY_AT_MOST:
        reasons.append(
            f"median {after.median_seconds} s against {before.median_seconds} s: "
            f"more than {SLOWER_BY_AT_MOST - 1:.0%} slower"
        )
    return not reasons, reasons


def compare(before: Arm, after: Arm) -> str:
    worse, better = flips(before, after)
    lines = [f"{'':24} {before.name:>16} {after.name:>16}"]
    for label, b, a in [
        (
            "cases passed (mean)",
            f"{before.passed_cases:.1f}/{before.cases}",
            f"{after.passed_cases:.1f}/{after.cases}",
        ),
        ("model seconds (median)", f"{before.median_seconds}", f"{after.median_seconds}"),
        ("model calls (median)", f"{before.median_calls:g}", f"{after.median_calls:g}"),
        ("tools sent (median)", f"{before.median_tools_sent:g}", f"{after.median_tools_sent:g}"),
    ]:
        lines.append(f"{label:24} {b:>16} {a:>16}")
    lines.append("")
    lines.append(f"Always passed, now always fails: {', '.join(worse) or 'none'}")
    lines.append(f"Always failed, now always passes: {', '.join(better) or 'none'}")
    differing = [
        f"  {case}: {before.counts[case][0]}/{before.counts[case][1]} -> "
        f"{after.counts[case][0]}/{after.counts[case][1]}"
        for case in sorted(before.counts.keys() & after.counts.keys())
        if case not in worse + better
        and before.counts[case][0] / before.counts[case][1]
        != after.counts[case][0] / after.counts[case][1]
    ]
    if differing:
        lines.append("Changed, but not every run (likely noise):")
        lines += differing
    wins, reasons = verdict(before, after)
    lines.append("")
    if wins:
        lines.append(f"Verdict: {after.name} wins under the agreed rule.")
    else:
        lines.append(f"Verdict: {before.name} stays.")
        lines += [f"  - {r}" for r in reasons]
    return "\n".join(lines)


def main(before_path: Path, after_path: Path) -> str:
    before_details, before = load_run(before_path)
    after_details, after = load_run(after_path)
    names = [before_details["routing"], after_details["routing"]]
    if names[0] == names[1]:
        names = [before_path.stem, after_path.stem]
    return compare(arm(names[0], before), arm(names[1], after))


if __name__ == "__main__":
    print(main(Path(sys.argv[1]), Path(sys.argv[2])))
