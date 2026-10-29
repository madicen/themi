"""AI behaviour evals: real models, the full app, a fake Telegram. Opt-in.

    make evals PROVIDER=gemini

Each case from cases.json runs in a fresh household: optional setup, one
message, then the tool calls and replies are scored (tests/evals/scoring.py).
Pass rates by category are printed at the end and saved under results/.
"""

from __future__ import annotations

import asyncio

import pytest

from tests.evals.conftest import OUTCOMES
from tests.evals.pacing import PacedFactory
from tests.evals.providers import EvalBackend
from tests.evals.runner import missing_tools, needs_gmail, needs_wall, run_case
from tests.evals.scoring import Case, load_cases
from tests.fakes.telegram_api import FakeTelegram
from tests.fixtures.family import SeededFamily
from tests.scenarios.harness import Scenario

CASES = load_cases()
GIVE_UP_AFTER = 3  # cases in a row with no AI answer: the quota is gone, stop spending it


@pytest.mark.parametrize("case", CASES, ids=[c.id for c in CASES])
async def test_case(
    case: Case,
    family: SeededFamily,
    fake_telegram: FakeTelegram,
    eval_backend: EvalBackend,
    eval_factory: PacedFactory,
    request: pytest.FixtureRequest,
) -> None:
    recent = OUTCOMES[-GIVE_UP_AFTER:]
    if len(recent) == GIVE_UP_AFTER and all(o.unavailable for o in recent):
        pytest.skip(f"the last {GIVE_UP_AFTER} cases got no AI answer (quota used up?)")
    google, gmail = (
        (request.getfixturevalue("fake_google"), request.getfixturevalue("fake_gmail"))
        if needs_gmail(case)
        else (None, None)
    )
    wall = request.getfixturevalue("fake_cozyla") if needs_wall(case) else None
    scenario = Scenario(
        family,
        fake_telegram,
        google,
        gmail,
        cozyla=wall,
        real_models=True,
        provider_factory=eval_factory,
    )
    missing = missing_tools(scenario, case)
    if missing:
        pytest.skip(f"needs {', '.join(missing)}, which isn't built yet")
    try:
        outcome = await run_case(scenario, case, eval_backend)
    finally:
        if eval_backend.pace:
            await asyncio.sleep(eval_backend.pace)  # opt-in evals only: free-tier rate limits
    OUTCOMES.append(outcome)
    if outcome.unavailable:
        pytest.skip("; ".join(outcome.problems))
    assert outcome.passed, "; ".join(outcome.problems)
