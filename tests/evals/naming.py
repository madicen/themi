"""P8a: an offline eval of the "which task?" naming check. No model: each case is a message
(with Themi's message before it, and their own before that, when they matter), the open
tasks, and the ones it means. The check is tried with each open task as the one the model
picked, and should let through exactly the ones meant.

- Wrongly refused: a task it means, refused (bug #119, "I ran this morning").
- Wrongly accepted: a task it doesn't mean, let through (#92, the bins for "We contacted
  Erin's parents").

A check is anything shaped like `word_check`: a case and a task title in, accepted or not.
Today's word check is the baseline; P8b's embedding fallback is scored the same way.
The cases are paraphrases of the kinds of thing the family says, with no names, places,
health or money details of theirs. `make naming-eval` prints the table.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from themi.core.tasks import meant_instead, names_task
from themi.core.which_task import Said, texts_to_score, which

NAMING_FILE = Path(__file__).parent / "naming_cases.json"
KINDS = ("plain", "paraphrase", "short-answer", "all", "near-miss")


@dataclass(frozen=True)
class NamingCase:
    id: str
    kind: str
    message: str
    before: str  # Themi's last message to them ("" if it doesn't matter)
    earlier: str  # their own message before this one
    tasks: tuple[str, ...]  # the open tasks
    means: tuple[str, ...]  # the ones it's about (none: it's about no open task)


Check = Callable[[NamingCase, str], bool]


@dataclass(frozen=True)
class Title:
    title: str


def word_check(case: NamingCase, tried: str) -> bool:
    """complete_task's naming checks: refused when what they said names another task
    instead (`_check_meant`), or names nothing of this one (`_named`)."""
    others = [Title(t) for t in case.tasks if t != tried]
    if meant_instead(tried, others, case.message, case.before) is not None:
        return False
    return names_task(tried, case.message, case.earlier, case.before)


def said_of(case: NamingCase) -> Said:
    return Said(case.message, case.earlier, case.before)


def texts_needed(cases: Sequence[NamingCase]) -> list[str]:
    """Every text P8b's check embeds for these cases: what's scored, and the titles."""
    texts = [t for c in cases for t in texts_to_score(said_of(c), dict(enumerate(c.tasks)))]
    return list(dict.fromkeys([*texts, *(t for c in cases for t in c.tasks)]))


def meaning_check(sims: Mapping[str, Mapping[str, float]], **settings: float) -> Check:
    """P8b's check (`which_task.which`), from each text's similarity to each title."""

    def check(case: NamingCase, tried: str) -> bool:
        titles = dict(enumerate(case.tasks))
        said = said_of(case)
        scored = {
            text: {i: sims[text][title] for i, title in titles.items()}
            for text in texts_to_score(said, titles)
        }
        return case.tasks.index(tried) in which(said, titles, scored, **settings)

    return check


def load_naming_cases(path: Path = NAMING_FILE, *, drafts: bool = False) -> list[NamingCase]:
    """The reviewed cases; or, with `drafts`, only the ones still waiting for a person to
    check their labels (`"reviewed": false`), which don't count until then."""
    raw = json.loads(path.read_text())
    board = tuple(raw["board"])
    return [
        NamingCase(
            id=item["id"],
            kind=item["kind"],
            message=item["message"],
            before=item.get("before", ""),
            earlier=item.get("earlier", ""),
            tasks=tuple(item.get("tasks", board)),
            means=tuple(item["means"]),
        )
        for item in raw["cases"]
        if item.get("reviewed", True) != drafts
    ]


@dataclass(frozen=True)
class Scored:
    case: NamingCase
    wrongly_refused: tuple[str, ...]
    wrongly_accepted: tuple[str, ...]

    @property
    def right(self) -> bool:
        return not self.wrongly_refused and not self.wrongly_accepted


def score(cases: Sequence[NamingCase], check: Check) -> list[Scored]:
    scored = []
    for case in cases:
        accepted = {t for t in case.tasks if check(case, t)}
        scored.append(
            Scored(
                case,
                tuple(t for t in case.means if t not in accepted),
                tuple(t for t in case.tasks if t in accepted and t not in case.means),
            )
        )
    return scored


@dataclass(frozen=True)
class Totals:
    cases: int
    right: int
    wrongly_refused: int  # cases with a meant task refused
    wrongly_accepted: int  # cases with a task let through that it doesn't mean


def totals(scored: Sequence[Scored]) -> Totals:
    return Totals(
        cases=len(scored),
        right=sum(s.right for s in scored),
        wrongly_refused=sum(bool(s.wrongly_refused) for s in scored),
        wrongly_accepted=sum(bool(s.wrongly_accepted) for s in scored),
    )


def format_naming(scored: Sequence[Scored]) -> str:
    lines = [f"{'kind':<14}{'cases':>7}{'right':>7}{'refused':>9}{'accepted':>10}"]
    for kind in KINDS:
        t = totals([s for s in scored if s.case.kind == kind])
        if t.cases:
            lines.append(
                f"{kind:<14}{t.cases:>7}{t.right:>7}{t.wrongly_refused:>9}{t.wrongly_accepted:>10}"
            )
    t = totals(scored)
    lines.append(
        f"{'all':<14}{t.cases:>7}{t.right:>7}{t.wrongly_refused:>9}{t.wrongly_accepted:>10}"
    )
    lines.append("(refused: a meant task wrongly refused; accepted: another task let through)")
    for s in scored:
        if s.wrongly_refused:
            lines.append(
                f"  {s.case.id}: {s.case.message!r} refused {', '.join(s.wrongly_refused)}"
            )
    for s in scored:
        if s.wrongly_accepted:
            lines.append(
                f"  {s.case.id}: {s.case.message!r} accepted {', '.join(s.wrongly_accepted)}"
            )
    return "\n".join(lines)
