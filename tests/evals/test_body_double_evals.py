"""BD1b: steps a real model proposes for a guided body double session. Opt-in, like the
other evals:

    make evals EVAL_ARGS='-k body_double_steps'

Each job passes when its steps are at most 12, short (eight words at most), plain actions
(no "you should", "make sure", "try to"), and, where the job has an order, in that order.
"""

from __future__ import annotations

import asyncio
import json
import re

from tests.evals.pacing import PacedFactory
from tests.evals.providers import EvalBackend
from tests.evals.runner import use_backend
from tests.fakes.telegram_api import FakeTelegram
from tests.fixtures.family import SeededFamily
from tests.scenarios.harness import Scenario
from themi.core.body_double import GUIDED

# (the job, words that must come in this order, each found in some step)
JOBS: list[tuple[str, tuple[str, ...]]] = [
    ("do the laundry", ("wash", "dry", "fold")),
    ("clean the kitchen", ()),
    ("pay the electricity bill", ("log", "pay")),
    ("make the bed", ()),
    ("write the thank-you cards", ("write", "stamp")),
    ("tidy the living room", ()),
]
NEEDED = 5
SHOULD = re.compile(r"\byou should\b|\bmake sure\b|\btry to\b|\bdon'?t forget\b", re.IGNORECASE)


def problems(steps: list[str], order: tuple[str, ...]) -> list[str]:
    found = []
    if not 1 <= len(steps) <= 12:
        found.append(f"{len(steps)} steps")
    for step in steps:
        words = re.sub(r"\(optional/bonus\)", "", step, flags=re.IGNORECASE).split()
        if len(words) > 8:
            found.append(f"long: {step!r}")
        if SHOULD.search(step):
            found.append(f"advice: {step!r}")
    joined = [s.lower() for s in steps]
    places = [next((i for i, s in enumerate(joined) if w in s), -1) for w in order]
    if order and (-1 in places or places != sorted(places)):
        found.append(f"order {order} at {places}")
    return found


async def test_body_double_steps(
    family: SeededFamily,
    fake_telegram: FakeTelegram,
    eval_backend: EvalBackend,
    eval_factory: PacedFactory,
) -> None:
    scenario = Scenario(family, fake_telegram, real_models=True, provider_factory=eval_factory)
    use_backend(scenario, eval_backend)
    await scenario.start()
    misses = []
    try:
        body_double = scenario.app.services.body_double
        assert body_double is not None
        erin = scenario.member("Erin")
        for job, order in JOBS:
            session, _, _ = await body_double.start(erin, mode=GUIDED, label=job)
            steps = list(json.loads(session.row["steps"] or "[]"))
            if found := problems(steps, order):
                misses.append(f"{job}: {'; '.join(found)} ({steps})")
            if eval_backend.pace:
                await asyncio.sleep(eval_backend.pace)
    finally:
        await scenario.stop()
    print(f"\nbody double steps: {len(JOBS) - len(misses)}/{len(JOBS)}")
    for miss in misses:
        print("  missed", miss)
    assert len(JOBS) - len(misses) >= NEEDED, "; ".join(misses)
