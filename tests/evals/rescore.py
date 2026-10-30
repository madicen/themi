"""Score a saved eval run again with today's cases and scoring, without calling a model.

    .venv/bin/python -m tests.evals.rescore tests/evals/results/gemini-....json

Changing an expectation or the scorer shouldn't cost quota: the saved run has
every tool call and reply, so it can be re-scored as often as needed. Repeats and
timings (P5) come back as they were saved.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from tests.evals.scoring import (
    Outcome,
    format_summary,
    load_cases,
    model_replies,
    score,
    summarise,
)


def load_run(path: Path) -> tuple[dict[str, Any], list[Outcome]]:
    """The saved run's details (provider, routing) and its outcomes, scored again."""
    saved = json.loads(path.read_text())
    cases = {c.id: c for c in load_cases()}
    strength = {"Erin": 2, "Husband": 1}  # as in the seeded family (tests/fixtures/family.py)
    outcomes = []
    for item in saved["cases"]:
        case = cases.get(item["id"])
        if case is None:
            continue  # a case removed since
        sent = item.get("sent") or item["replies"]
        replies = model_replies([tuple(s) for s in sent] if item.get("sent") else sent)
        calls = [(name, args) for name, args in item["calls"]]
        outcome = score(case, calls, replies, strength[case.speaker])
        outcome.run = item.get("run", 1)
        outcome.model_seconds = item.get("model_seconds", [])
        outcome.tools_sent = item.get("tools_sent", 0)
        outcome.tools_chars = item.get("tools_chars", 0)
        outcomes.append(outcome)
    details = {"provider": saved["provider"], "routing": saved.get("routing", "groups")}
    return details, outcomes


def rescore(path: Path) -> str:
    details, outcomes = load_run(path)
    name = f"{details['provider']}, {details['routing']} tools (re-scored)"
    lines = [format_summary(name, summarise(outcomes))]
    lines += [f"  {o.case.id}: {'; '.join(o.problems)}" for o in outcomes if not o.passed]
    return "\n".join(lines)


if __name__ == "__main__":
    print(rescore(Path(sys.argv[1])))
