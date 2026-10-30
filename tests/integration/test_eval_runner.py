"""A dry run of the eval runner: the real Gemini adapter, over HTTP, against a fake Gemini.

This proves the eval plumbing (backends, tool recording, reply capture, scoring)
without a key. `make evals` runs the same code against the real service.
"""

from __future__ import annotations

from tests.evals.providers import EvalBackend
from tests.evals.runner import needs_gmail, needs_wall, run_case
from tests.evals.scoring import load_cases
from tests.fakes.cozyla import FakeCozyla
from tests.fakes.gmail_api import FakeGmail
from tests.fakes.google_oauth import FakeGoogle
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


async def test_the_noise_setup_leaves_offers_waiting(
    family: SeededFamily,
    fake_telegram: FakeTelegram,
    fake_ai: FakeAIServer,
    fake_google: FakeGoogle,
    fake_gmail: FakeGmail,
) -> None:
    # The #67 cases: emails waiting to be archived, then "archive the LOFT one".
    case = CASES["email-noise-archive-them"]
    assert needs_gmail(case)
    fake_ai.queue(
        gemini_function_call("archive_noise_emails", {"answer": "archive", "which": ["loft"]})
    )
    fake_ai.queue(gemini_text("Archived it."))
    scenario = Scenario(family, fake_telegram, fake_google, fake_gmail, real_models=True)
    outcome = await run_case(scenario, case, fake_gemini(fake_ai))
    assert outcome.passed, outcome.problems
    body = fake_ai.requests[0].json
    assert "Emails that look like noise, 2 waiting" in str(body)
    statuses = [r["status"] for r in family.db.query("SELECT status FROM pending_actions")]
    assert sorted(statuses) == ["done", "pending"]


async def test_the_routine_setup_puts_items_on_the_fake_wall(
    family: SeededFamily,
    fake_telegram: FakeTelegram,
    fake_ai: FakeAIServer,
    fake_cozyla: FakeCozyla,
) -> None:
    # F18b's case: "What is my morning routine?" reads the wall (bugs #76, #78).
    case = CASES["wall-what-is-my-morning-routine"]
    assert needs_wall(case)
    fake_ai.queue(gemini_function_call("show_routine", {"part": "Morning"}))
    fake_ai.queue(gemini_text("Your morning routine: walk the dog, then make the bed."))
    scenario = Scenario(family, fake_telegram, cozyla=fake_cozyla, real_models=True)
    outcome = await run_case(scenario, case, fake_gemini(fake_ai))
    assert outcome.passed, outcome.problems
    result = str(fake_ai.requests[1].json)
    assert "Morning routine on the wall, today: Walk dog, Make the bed" in result


async def test_each_model_call_is_timed_and_the_tools_counted(
    family: SeededFamily, fake_telegram: FakeTelegram, fake_ai: FakeAIServer
) -> None:
    # P5: timings per case, and what the first call sent.
    fake_ai.queue(gemini_function_call("log_energy_note", {"effect": -2, "note": "client call"}))
    fake_ai.queue(gemini_text("That sounds draining."))
    scenario = Scenario(family, fake_telegram, real_models=True)
    outcome = await run_case(scenario, CASES["energy-client-call"], fake_gemini(fake_ai), run=2)
    assert outcome.run == 2
    assert len(outcome.model_seconds) == 2 and all(s >= 0 for s in outcome.model_seconds)
    declared = fake_ai.requests[0].json["tools"][0]["functionDeclarations"]
    assert outcome.tools_sent == len(declared)
    assert outcome.tools_chars > 1000


async def test_every_tool_routing_sends_them_all_without_more_tools(
    family: SeededFamily, fake_telegram: FakeTelegram, fake_ai: FakeAIServer
) -> None:
    fake_ai.queue(gemini_text("Hi!"))
    every = Scenario(family, fake_telegram, real_models=True, tool_routing="all")
    outcome = await run_case(every, CASES["energy-client-call"], fake_gemini(fake_ai))
    names = [d["name"] for d in fake_ai.requests[-1].json["tools"][0]["functionDeclarations"]]
    assert "more_tools" not in names and "update_pantry" in names
    registry = every.app.services.tools
    assert len(names) == len(registry.specs()) - 1 > len(registry.specs(set()))
    assert outcome.tools_sent == len(names)


async def test_the_list_setup_makes_a_named_list(
    family: SeededFamily, fake_telegram: FakeTelegram, fake_ai: FakeAIServer
) -> None:
    # P6's twins cases: "add sunscreen to the packing list" needs the list to be there.
    fake_ai.queue(gemini_function_call("add_to_list", {"list": "packing", "items": ["sunscreen"]}))
    fake_ai.queue(gemini_text("Sunscreen is on Packing."))
    scenario = Scenario(family, fake_telegram, real_models=True)
    outcome = await run_case(scenario, CASES["twin-list-packing"], fake_gemini(fake_ai))
    assert outcome.passed, outcome.problems
    assert "Packing" in str(fake_ai.requests[1].json)
