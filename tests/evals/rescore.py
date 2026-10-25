"""Score a saved eval run again with today's cases and scoring, without calling a model.

    .venv/bin/python -m tests.evals.rescore tests/evals/results/gemini-....json

Changing an expectation or the scorer shouldn't cost quota: the saved run has
every tool call and reply, so it can be re-scored as often as needed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from tests.evals.scoring import format_summary, load_cases, model_replies, score, summarise


def rescore(path: Path) -> str:
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
        outcomes.append(score(case, calls, replies, strength[case.speaker]))
    lines = [format_summary(f"{saved['provider']} (re-scored)", summarise(outcomes))]
    lines += [f"  {o.case.id}: {'; '.join(o.problems)}" for o in outcomes if not o.passed]
    return "\n".join(lines)


if __name__ == "__main__":
    print(rescore(Path(sys.argv[1])))
