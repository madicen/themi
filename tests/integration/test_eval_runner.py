"""A dry run of the eval runner: the real Gemini adapter, over HTTP, against a fake Gemini.

This proves the eval plumbing (backends, tool recording, reply capture, scoring)
without a key. `make evals` runs the same code against the real service.
"""

from __future__ import annotations

from tests.evals.providers import EvalBackend
from tests.evals.runner import run_case
from tests.evals.scoring import load_cases
from tests.fakes.http_ai import FakeAIServer, gemini_function_call, gemini_text
from tests.fakes.telegram_api import FakeTelegram
from tests.fixtures.family import SeededFamily
from tests.scenarios.harness import Scenario
from themi.storage.secrets import Secret

CASES = {c.id: c for c in load_cases()}


def fake_gemini(fake_ai: FakeAIServer) -> EvalBackend:
    return EvalBackend("gemini", "gemini", base_url=fake_ai.url, api_key=Secret("test-key"))


async def test_a_case_runs_through_the_real_adapter_and_is_scored(
    family: SeededFamily, fake_telegram: FakeTelegram, fake_ai: FakeAIServer
) -> None:
    fake_ai.queue(gemini_function_call("log_energy_note", {"effect": -2, "note": "client call"}))
    fake_ai.queue(gemini_text("That sounds draining. Hope the afternoon is gentler."))
    scenario = Scenario(family, fake_telegram, real_models=True)
    outcome = await run_case(scenario, CASES["energy-client-call"], fake_gemini(fake_ai))
    assert outcome.calls == [("log_energy_note", {"effect": -2, "note": "client call"})]
    assert outcome.replies == ["That sounds draining. Hope the afternoon is gentler."]
    assert outcome.passed, outcome.problems
    assert "generateContent" in fake_ai.requests[0].path


async def test_a_wrong_or_demanding_answer_fails(
    family: SeededFamily, fake_telegram: FakeTelegram, fake_ai: FakeAIServer
) -> None:
    fake_ai.queue(gemini_text("You need to rest now. Your energy is at 20%."))
    scenario = Scenario(family, fake_telegram, real_models=True)
    outcome = await run_case(scenario, CASES["energy-client-call"], fake_gemini(fake_ai))
    assert not outcome.tools_ok and not outcome.pda_ok
    assert "expected one of log_energy_note, log_energy_level" in outcome.problems
    assert any(p.startswith("looks like a score") for p in outcome.problems)
