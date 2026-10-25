"""Side-effect tools can only act through the trust tiers."""

from typing import Any

import pytest

from tests.fixtures.family import SeededFamily
from themi.ai.types import ToolCall, ToolSpec
from themi.autonomy import Autonomy, ExecutionContext, ExecutorRegistry
from themi.core.tools import Proposal, Tool, ToolContext, ToolRegistry, staged_tool, tool


@staged_tool(
    "archive_promos",
    "Archive promotional emails",
    {"count": {"type": "integer"}},
)
async def archive_promos(ctx: ToolContext, args: dict[str, Any]) -> Proposal:
    return Proposal(
        "email_archive_noise",
        f"Archive {args['count']} promo emails",
        "gmail.archive",
        {"count": args["count"]},
    )


class FakeServices:
    def __init__(self, autonomy: Autonomy) -> None:
        self.autonomy = autonomy


@pytest.fixture
def setup(family: SeededFamily):
    executed: list[dict] = []
    executors = ExecutorRegistry()

    @executors.register("gmail.archive")
    async def archive(payload: dict[str, Any], ctx: ExecutionContext) -> str:
        executed.append(payload)
        return "Archived."

    autonomy = Autonomy(family.store, executors)
    ctx = ToolContext(family.erin, FakeServices(autonomy))  # type: ignore[arg-type]
    return autonomy, ctx, executed


def test_side_effect_tools_built_any_other_way_are_refused() -> None:
    async def direct(ctx: ToolContext, args: dict[str, Any]) -> str:
        return "sent the email"

    sneaky = Tool(ToolSpec("send_email", "Send", {"type": "object"}, side_effect=True), direct)
    with pytest.raises(ValueError, match="staged_tool"):
        ToolRegistry([sneaky])
    mislabelled = Tool(ToolSpec("noop", "x", {"type": "object"}), direct, proposes=True)
    with pytest.raises(ValueError):
        ToolRegistry([mislabelled])


async def test_a_staged_tool_waits_for_approval_at_tier_1(setup) -> None:
    autonomy, ctx, executed = setup
    result = await ToolRegistry([archive_promos]).run(
        ToolCall("c1", "archive_promos", {"count": 4}), ctx
    )
    assert not result.is_error
    assert result.content.startswith("Staged for approval (action 1): Archive 4 promo emails")
    assert "don't describe it as done" in result.content
    assert executed == [] and autonomy.action(1).status == "pending"


async def test_a_staged_tool_runs_at_once_at_tier_2(setup, family: SeededFamily) -> None:
    autonomy, ctx, executed = setup
    autonomy.grant_tier2("email_archive_noise", via_rule_id=1, by=family.erin)
    result = await ToolRegistry([archive_promos]).run(
        ToolCall("c1", "archive_promos", {"count": 2}), ctx
    )
    assert result.content == "Done automatically (action 1): Archived."
    assert executed == [{"count": 2}]


async def test_a_staged_tool_that_doesnt_propose_is_an_error(setup) -> None:
    @staged_tool("bad", "Returns text instead of a proposal", {})
    async def bad(ctx: ToolContext, args: dict[str, Any]) -> str:
        return "I did it myself"

    _autonomy, ctx, executed = setup
    result = await ToolRegistry([bad]).run(ToolCall("c1", "bad", {}), ctx)
    assert result.is_error and executed == []


async def test_a_read_only_tool_cant_return_a_proposal(setup) -> None:
    @tool("sneaky", "Looks harmless", {})
    async def sneaky(ctx: ToolContext, args: dict[str, Any]) -> Proposal:
        return Proposal("email_reply", "send it", "gmail.archive")

    autonomy, ctx, executed = setup
    result = await ToolRegistry([sneaky]).run(ToolCall("c1", "sneaky", {}), ctx)
    assert result.is_error and executed == []
    assert autonomy.audit_trail() == []
