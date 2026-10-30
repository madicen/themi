"""Running one eval case in a fresh household (shared by the evals and their dry run)."""

from __future__ import annotations

import json
import time
from collections.abc import Sequence
from typing import Any

from tests.evals.pacing import PacedFactory
from tests.evals.providers import EvalBackend
from tests.evals.scoring import Case, Outcome, model_replies, score
from tests.fakes.google_oauth import _Refresh
from tests.scenarios.harness import Scenario
from themi.accounts import Member
from themi.ai.settings import AITask, RouteEntry
from themi.connectors.google.oauth import LINK_SCOPES
from themi.core.groceries import list_summary
from themi.storage.secrets import Secret


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
        elif "list" in step:
            assert services.lists is not None
            services.lists.create(member, step["list"], personal=False)
        elif "noise" in step:
            await _noise(scenario, member, step["noise"])
        elif "routine" in step:
            assert scenario.cozyla is not None, "a routine case needs the fake wall"
            uid = f"m-{case.speaker.lower()}"
            for item in step["routine"]:
                scenario.cozyla.add_routine(uid, item["title"], item["part"])
        else:
            raise ValueError(f"unknown setup step {step}")


def needs_gmail(case: Case) -> bool:
    return any("noise" in step for step in case.setup)


def needs_wall(case: Case) -> bool:
    """A case about the wall's routines gets the fake Cozyla (F18b's show_routine)."""
    return any("routine" in step for step in case.setup)


async def _noise(scenario: Scenario, member: Member, mails: list[dict[str, str]]) -> None:
    """Their inbox, linked and synced, with these emails offered for archiving as noise, as
    triage leaves them (bug #67). Needs the Scenario built with the fake Gmail."""
    services = scenario.app.services
    google = scenario.google
    assert google is not None and services.gmail is not None, "this case needs fake Gmail"
    address = f"{member.name.lower()}@gmail.com"
    token = f"eval-refresh-{member.id}"
    google.state.refresh_tokens[token] = _Refresh(address, LINK_SCOPES)
    account = scenario.app.store.add_linked_account(
        member, member.id, "gmail", address, Secret(token)
    )
    scenario.app.store.update_linked_account(member, account.id, watched=True)
    gmail = scenario.gmail
    assert gmail is not None
    for mail in mails:
        gmail.deliver(address, sender=mail["sender"], subject=mail["subject"], text=".")
    await scenario.run_periodic("gmail.poll")
    for row in scenario.app.db.query(
        "SELECT * FROM emails WHERE account_id = ? ORDER BY id", (account.id,)
    ):
        await services.autonomy.stage(
            "email_archive_noise",
            member,
            f"Probably noise, to archive: {row['subject']} (from {row['from_name']})",
            {"email_id": row["id"]},
            "gmail.archive",
        )


def missing_tools(scenario: Scenario, case: Case) -> list[str]:
    return [t for t in case.requires if scenario.app.services.tools.get(t) is None]


def tools_size(tools: Sequence[Any]) -> int:
    """The tools' schemas as characters, roughly as they go to the model."""
    return len(
        json.dumps(
            [
                {"name": t.name, "description": t.description, "schema": t.input_schema}
                for t in tools
            ]
        )
    )


async def run_case(
    scenario: Scenario,
    case: Case,
    chosen: EvalBackend,
    paced: PacedFactory | None = None,
    run: int = 1,
) -> Outcome:
    """Set up, send the message, and score the tool calls and replies. Each model call is
    timed with the real clock (Themi's is frozen), less any wait for the per-minute pace."""
    use_backend(scenario, chosen)
    await scenario.start()
    calls: list[tuple[str, dict[str, Any]]] = []
    steps: list[int] = []
    model_steps = [0]
    seconds: list[float] = []
    sent_tools: list[Sequence[Any]] = []
    registry = scenario.app.services.tools
    original = registry.run
    router = scenario.app.services.router
    original_client = router.client_for

    async def recording(call, ctx):  # type: ignore[no-untyped-def]
        calls.append((call.name, dict(call.arguments)))
        steps.append(model_steps[0])
        return await original(call, ctx)

    def counting_client(member_id, task):  # type: ignore[no-untyped-def]
        client = original_client(member_id, task)
        chat = client.chat

        async def counted(*args, **kwargs):  # type: ignore[no-untyped-def]
            model_steps[0] += 1
            tools = args[2] if len(args) > 2 else kwargs.get("tools", ())
            if tools and not sent_tools:
                sent_tools.append(tools)
            began, waited = time.monotonic(), paced.waited if paced else 0.0
            try:
                return await chat(*args, **kwargs)
            finally:
                pacing = (paced.waited if paced else 0.0) - waited
                seconds.append(round(time.monotonic() - began - pacing, 2))

        client.chat = counted  # type: ignore[method-assign]
        return client

    registry.run = recording  # type: ignore[method-assign]
    router.client_for = counting_client  # type: ignore[method-assign]
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
        outcome.call_steps = steps
        outcome.run = run
        outcome.model_seconds = seconds
        if sent_tools:
            outcome.tools_sent = len(sent_tools[0])
            outcome.tools_chars = tools_size(sent_tools[0])
        return outcome
    finally:
        await scenario.stop()
