"""Scoring one eval case: pure functions, so they're unit-tested without a model."""

from __future__ import annotations

import json
import re
import statistics
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from themi.channels.pda import find_demands, split_quotes
from themi.core.agent import BUSY_TEXT

CASES_FILE = Path(__file__).with_name("cases.json")
# Energy is only ever words: no numbers that look like a score.
# Lookups that change nothing: calling one is never a mistake.
# Tools that change nothing, so any case may call them. more_tools (P1) only brings in
# another group's tools.
READ_ONLY_TOOLS = frozenset(
    {"list_open_items", "show_pantry", "show_grocery_list", "list_expected_emails", "more_tools"}
)
APPROVAL_ASK = "Go ahead, or not now?"
SCORE_PATTERN = re.compile(r"(?i)\b\d{1,3}\s?(%|/\s?100|out of 100)|\bcapacity\b|\benergy score\b")


@dataclass(frozen=True)
class Case:
    id: str
    category: str
    message: str
    speaker: str = "Erin"
    expect: tuple[str, ...] = ()
    expect_any: tuple[str, ...] = ()  # at least one of these
    allow: tuple[str, ...] = ()
    forbid: tuple[str, ...] = ()
    args: dict[str, dict[str, Any]] = field(default_factory=dict, hash=False)
    reply_must: str | None = None
    reply_must_not: str | None = None
    requires: tuple[str, ...] = ()
    setup: tuple[dict[str, Any], ...] = ()


def load_cases(path: Path = CASES_FILE) -> list[Case]:
    raw = json.loads(path.read_text())["cases"]
    cases = []
    for item in raw:
        cases.append(
            Case(
                id=item["id"],
                category=item["category"],
                message=item["message"],
                speaker=item.get("from", "Erin"),
                expect=tuple(item.get("expect", [])),
                expect_any=tuple(item.get("expect_any", [])),
                allow=tuple(item.get("allow", [])),
                forbid=tuple(item.get("forbid", [])),
                args=item.get("args", {}),
                reply_must=item.get("reply_must"),
                reply_must_not=item.get("reply_must_not"),
                requires=tuple(item.get("requires", [])),
                setup=tuple(item.get("setup", [])),
            )
        )
    return cases


# A tool that sends the answer itself (the day's summary, the few things for now, O1a):
# that message is the reply, and the model rightly adds little or nothing.
ANSWER_KINDS = ("summary", "focus")


def model_replies(sent: list[tuple[str, str]] | list[str]) -> list[str]:
    """The replies, from (kind, text) pairs: the model's own, and a tool's answer sent as it
    is. Themi's own approval cards and rule proposals are templates, not replies. Older
    saved runs have bare texts; approval cards are recognised by their ask."""
    replies = []
    for entry in sent:
        if isinstance(entry, str):
            if not entry.rstrip().endswith(APPROVAL_ASK):
                replies.append(entry)
        elif entry[0] == "chat" or entry[0] in ANSWER_KINDS:
            replies.append(entry[1])
    return replies


@dataclass
class Outcome:
    case: Case
    tools_ok: bool
    pda_ok: bool
    problems: list[str]
    calls: list[tuple[str, dict[str, Any]]]
    replies: list[str]
    unavailable: bool = False  # no model answered: says nothing about behaviour
    sent: list[tuple[str, str]] = field(default_factory=list)  # everything, with its kind
    # For each call, which model step asked for it (calls sharing a step came together).
    call_steps: list[int] = field(default_factory=list)
    run: int = 1  # P5: which repeat of the case this was
    model_seconds: list[float] = field(default_factory=list)  # each model call, not pacing
    tools_sent: int = 0  # with the first conversation call
    tools_chars: int = 0  # the same tools' schemas, as characters

    @property
    def passed(self) -> bool:
        return self.tools_ok and self.pda_ok and not self.unavailable


def _check_arg(value: Any, rule: dict[str, Any]) -> bool:
    if isinstance(value, str) and ("lt" in rule or "gt" in rule):
        try:  # "-3": the tools read a number sent as text as that number (energy-plumber)
            value = float(value)
        except ValueError:
            return False
    if "lt" in rule:
        return isinstance(value, int | float) and value < rule["lt"]
    if "gt" in rule:
        return isinstance(value, int | float) and value > rule["gt"]
    if "equals" in rule:
        return value == rule["equals"]
    if "contains" in rule:
        return str(rule["contains"]).lower() in str(value).lower()
    raise ValueError(f"unknown argument rule {rule}")


def score(
    case: Case,
    calls: list[tuple[str, dict[str, Any]]],
    replies: list[str],
    pda_strength: int,
) -> Outcome:
    if any(BUSY_TEXT in reply for reply in replies):
        problem = "no AI backend answered (quota, outage or rate limit)"
        return Outcome(case, False, False, [problem], calls, replies, unavailable=True)
    problems: list[str] = []
    names = [name for name, _ in calls]
    for wanted in case.expect:
        if wanted not in names:
            problems.append(f"expected a {wanted} call")
    if case.expect_any and not any(n in names for n in case.expect_any):
        problems.append(f"expected one of {', '.join(case.expect_any)}")
    permitted = {*case.expect, *case.expect_any, *case.allow, *READ_ONLY_TOOLS}
    for name in names:
        if name in case.forbid:
            problems.append(f"called {name}, which this case forbids")
        elif name not in permitted:
            problems.append(f"unexpected {name} call")
    for tool, rules in case.args.items():
        made = [args for name, args in calls if name == tool]
        if not made:
            continue  # already reported as missing
        for arg, rule in rules.items():
            if arg == "_json":
                text = " ".join(json.dumps(a).lower() for a in made)
                missing = [s for s in rule if s.lower() not in text]
                if missing:
                    problems.append(f"{tool} arguments don't mention {', '.join(missing)}")
            elif not any(_check_arg(a.get(arg), rule) for a in made):
                problems.append(f"{tool}.{arg} should be {rule}, got {[a.get(arg) for a in made]}")
    reply = "\n".join(replies)
    if not replies:
        problems.append("no reply")
    if case.reply_must and not re.search(case.reply_must, reply):
        problems.append(f"reply should match {case.reply_must!r}")
    if case.reply_must_not and re.search(case.reply_must_not, reply):
        problems.append(f"reply shouldn't match {case.reply_must_not!r}")
    tools_ok = not problems

    pda_problems = []
    for text in replies:
        own, _ = split_quotes(text)
        flags = find_demands(own, pda_strength)
        if flags:
            pda_problems.append(f"PDA: {', '.join(f.match for f in flags)} in {text[:80]!r}")
        if SCORE_PATTERN.search(own):
            pda_problems.append(f"looks like a score in {text[:80]!r}")
    problems.extend(pda_problems)
    return Outcome(case, tools_ok, not pda_problems, problems, calls, replies)


def _median(values: Sequence[float]) -> float:
    return round(statistics.median(values), 1) if values else 0.0


def per_case(outcomes: list[Outcome]) -> dict[str, tuple[int, int]]:
    """Each case's (passed, runs), over the runs a model answered."""
    counts: dict[str, tuple[int, int]] = {}
    for o in outcomes:
        if not o.unavailable:
            passed, runs = counts.get(o.case.id, (0, 0))
            counts[o.case.id] = (passed + o.passed, runs + 1)
    return counts


def summarise(outcomes: list[Outcome]) -> dict[str, Any]:
    """Pass rates by category, and overall, over the cases a model actually answered. With
    repeats (P5), each run counts, and cases that passed some runs and not others are
    flaky, apart from the ones that never passed."""
    categories: dict[str, dict[str, int]] = {}
    unavailable = sum(o.unavailable for o in outcomes)
    outcomes = [o for o in outcomes if not o.unavailable]
    for o in outcomes:
        c = categories.setdefault(o.case.category, {"cases": 0, "passed": 0, "tools": 0, "pda": 0})
        c["cases"] += 1
        c["passed"] += o.passed
        c["tools"] += o.tools_ok
        c["pda"] += o.pda_ok
    total = len(outcomes)
    counts = per_case(outcomes)
    timed = [o for o in outcomes if o.model_seconds]
    return {
        "categories": categories,
        "runs": max((runs for _, runs in counts.values()), default=0),
        "flaky": sorted(c for c, (passed, runs) in counts.items() if 0 < passed < runs),
        "failing": sorted(c for c, (passed, _) in counts.items() if passed == 0),
        "median_seconds": _median([sum(o.model_seconds) for o in timed]),
        "median_calls": _median([len(o.model_seconds) for o in timed]),
        "median_tools_sent": _median([o.tools_sent for o in timed]),
        "median_tools_chars": _median([o.tools_chars for o in timed]),
        "cases": total,
        "unavailable": unavailable,
        "passed": sum(o.passed for o in outcomes),
        "pass_rate": round(100 * sum(o.passed for o in outcomes) / total, 1) if total else 0.0,
        "pda_rate": round(100 * sum(o.pda_ok for o in outcomes) / total, 1) if total else 0.0,
    }


def format_summary(provider: str, summary: dict[str, Any]) -> str:
    lines = [
        f"Evals for {provider}: {summary['passed']}/{summary['cases']} passed "
        f"({summary['pass_rate']}%), PDA-safe replies {summary['pda_rate']}%"
    ]
    if summary.get("unavailable"):
        lines.append(f"{summary['unavailable']} couldn't run: no AI backend answered (not counted)")
    if summary.get("runs", 1) > 1:
        lines.append(f"Each case ran {summary['runs']} times; every run counts.")
    if summary.get("median_calls"):
        lines.append(
            f"Per case (median): {summary['median_seconds']} s in model calls, "
            f"{summary['median_calls']:g} calls, {summary['median_tools_sent']:g} tools sent "
            f"({summary['median_tools_chars']:g} characters)"
        )
    lines.append(f"{'category':16} {'pass':>9} {'tools':>9} {'pda':>9}")
    for name, c in sorted(summary["categories"].items()):
        n = c["cases"]
        lines.append(
            f"{name:16} {c['passed']:>4}/{n:<4} {c['tools']:>4}/{n:<4} {c['pda']:>4}/{n:<4}"
        )
    if summary.get("runs", 1) > 1 and summary.get("flaky"):
        lines.append(f"Flaky (passed some runs): {', '.join(summary['flaky'])}")
    if summary.get("runs", 1) > 1 and summary.get("failing"):
        lines.append(f"Failed every run: {', '.join(summary['failing'])}")
    return "\n".join(lines)
