"""Side effects in a real conversation go through the trust tiers."""

from typing import Any

from tests.scenarios.harness import Scenario
from themi.ai.types import ToolResult
from themi.autonomy import Decision, ExecutionContext
from themi.core.tools import Proposal, ToolContext, staged_tool


def install_archive_tool(scenario: Scenario) -> list[dict]:
    executed: list[dict] = []

    @scenario.app.services.autonomy.executors.register("gmail.archive")
    async def archive(payload: dict[str, Any], ctx: ExecutionContext) -> str:
        executed.append(payload)
        return "Archived the promos."

    @staged_tool("archive_promos", "Archive promotional emails", {"count": {"type": "integer"}})
    async def archive_promos(ctx: ToolContext, args: dict[str, Any]) -> Proposal:
        return Proposal(
            "email_archive_noise",
            f"Archive {args['count']} promo emails",
            "gmail.archive",
            {"count": args["count"]},
        )

    scenario.app.services.tools.register(archive_promos)
    return executed


async def test_the_model_can_only_stage_and_nothing_happens_without_a_yes(
    scenario: Scenario,
) -> None:
    executed = install_archive_tool(scenario)
    scenario.primary.queue_tool_call("archive_promos", {"count": 5})
    scenario.primary.queue_text("I've lined up archiving 5 promo emails for your okay.")
    replies = await scenario.say("Erin", "clear out the store promos")
    assert replies == ["I've lined up archiving 5 promo emails for your okay."]
    assert executed == []

    result = scenario.primary.last_request.messages[2].content[0]
    assert isinstance(result, ToolResult) and result.content.startswith("Staged for approval")

    autonomy = scenario.app.services.autonomy
    (action,) = autonomy.awaiting(scenario.member("Erin"))
    outcome = await autonomy.resolve(action.id, Decision.APPROVE, by=scenario.member("Erin"))
    assert outcome.message == "Archived the promos." and executed == [{"count": 5}]


def test_every_side_effect_tool_in_the_app_stages(scenario: Scenario) -> None:
    for spec in scenario.app.services.tools.specs():
        registered = scenario.app.services.tools.get(spec.name)
        assert registered is not None
        assert registered.spec.side_effect == registered.proposes, spec.name
