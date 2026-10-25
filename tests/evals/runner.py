"""Running one eval case in a fresh household (shared by the evals and their dry run)."""

from __future__ import annotations

from typing import Any

from tests.evals.providers import EvalBackend
from tests.evals.scoring import Case, Outcome, model_replies, score
from tests.scenarios.harness import Scenario
from themi.ai.settings import AITask, RouteEntry
from themi.core.groceries import list_summary


def use_backend(scenario: Scenario, chosen: EvalBackend) -> None:
    ai = scenario.app.ai_settings
    for name in ("Erin", "Husband"):
        member = scenario.member(name)
        models = [chosen.model] + ([chosen.fallback_model] if chosen.fallback_model else [])
        chain = []
        for n, model in enumerate(models, start=1):
            added = ai.add_backend(
                member,
                member.id,
                f"Eval {chosen.name} {n}",
                chosen.kind,
                model=model,
                base_url=chosen.base_url,
                api_key=chosen.api_key,
                supports_audio=False,
            )
            chain.append(RouteEntry(added.id))
        for task in AITask:
            if task is not AITask.TRANSCRIPTION:
                ai.set_chain(member, member.id, task, chain)


async def apply_setup(scenario: Scenario, case: Case) -> None:
    member = scenario.member(case.speaker)
    services = scenario.app.services
    for step in case.setup:
        if "stage_grocery" in step:
            items = list(step["stage_grocery"])
            await services.autonomy.stage(
                "grocery_list_add",
                member,
                list_summary(items),
                {"items": items},
                "groceries.add",
            )
        elif "task" in step:
            assert services.taskboard is not None
            await services.taskboard.create(member, step["task"], "errand", 1)
        else:
            raise ValueError(f"unknown setup step {step}")


def missing_tools(scenario: Scenario, case: Case) -> list[str]:
    return [t for t in case.requires if scenario.app.services.tools.get(t) is None]


async def run_case(scenario: Scenario, case: Case, chosen: EvalBackend) -> Outcome:
    """Set up, send the message, and score the tool calls and replies."""
    use_backend(scenario, chosen)
    await scenario.start()
    calls: list[tuple[str, dict[str, Any]]] = []
    registry = scenario.app.services.tools
    original = registry.run

    async def recording(call, ctx):  # type: ignore[no-untyped-def]
        calls.append((call.name, dict(call.arguments)))
        return await original(call, ctx)

    registry.run = recording  # type: ignore[method-assign]
    try:
        await apply_setup(scenario, case)
        member = scenario.member(case.speaker)
        mark = scenario.app.db.scalar("SELECT COALESCE(MAX(id), 0) FROM outbox")
        await scenario.say(case.speaker, case.message)
        sent = [
            (r["kind"], r["text"])
            for r in scenario.app.db.query(
                "SELECT kind, text FROM outbox WHERE id > ? AND member_id = ? "
                "AND priority = 'reply' ORDER BY id",
                (mark, member.id),
            )
        ]
        outcome = score(case, calls, model_replies(sent), member.pda_strength)
        outcome.sent = sent
        return outcome
    finally:
        await scenario.stop()
