"""CM1c: the sidecar against real models. Opt-in, like the other evals:

    make evals EVAL_ARGS='-k sidecar'

Each case in sidecar_cases.json runs in a fresh household: open tasks if the case has
them, then one sidecar pass over the message and the chat reply it lists (no chat call:
the reply is given). What went through is scored; precision and recall per kind are printed
at the end and saved under results/.
"""

from __future__ import annotations

import asyncio

import pytest

from tests.evals.conftest import SIDECAR_RESULTS
from tests.evals.pacing import PacedFactory
from tests.evals.providers import EvalBackend
from tests.evals.runner import use_backend
from tests.evals.sidecar import SidecarCase, load, score
from tests.fakes.telegram_api import FakeTelegram
from tests.fixtures.family import SeededFamily
from tests.scenarios.harness import Scenario
from tests.scenarios.test_triage import ERIN, link
from themi.core import keys

CASES = load()


@pytest.mark.parametrize("sidecar_case", CASES, ids=[c.id for c in CASES])
async def test_sidecar_case(
    sidecar_case: SidecarCase,
    family: SeededFamily,
    fake_telegram: FakeTelegram,
    eval_backend: EvalBackend,
    eval_factory: PacedFactory,
    request: pytest.FixtureRequest,
) -> None:
    case = sidecar_case
    google = request.getfixturevalue("fake_google") if case.requires_calendar else None
    gcal = request.getfixturevalue("fake_gcal") if case.requires_calendar else None
    scenario = Scenario(
        family, fake_telegram, google, gcal=gcal, real_models=True, provider_factory=eval_factory
    )
    use_backend(scenario, eval_backend)
    await scenario.start()
    try:
        if case.requires_calendar:
            from tests.fixtures.web import web_client

            async with web_client(scenario) as site:
                await link(scenario, site, google, "Erin", ERIN)  # type: ignore[arg-type]
        member = scenario.member(case.speaker)
        board = scenario.app.services.maybe(keys.taskboard)
        assert board is not None
        ids = {}
        for title in case.tasks:
            ids[title] = (await board.create(member, title, "call", 1, assignee=member)).id
        conversation = scenario.app.services.maybe(keys.conversation)
        assert conversation is not None
        items = await conversation.sidecar.run(member, case.message, case.reply, None, [])
        calls = [(i.tool, i.arguments) for i in items if i.outcome == "ok"]
        scored = score(case, calls, ids)
    finally:
        await scenario.stop()
        if eval_backend.pace:
            await asyncio.sleep(eval_backend.pace)  # opt-in evals only: free-tier rate limits
    SIDECAR_RESULTS.append(scored)
    problems = [f"missed {m}" for m in scored.misses] + [f"made {e}" for e in scored.extras]
    assert scored.passed, "; ".join(problems)
