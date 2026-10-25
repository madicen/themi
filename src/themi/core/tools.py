"""Tools the model can call.

Each tool has a closed JSON Schema (`additionalProperties: false`, every
property required), so Claude can run it in strict mode and local models in
JSON mode get the same contract. Arguments are validated again before the
handler runs; a bad call comes back to the model as an error result, never
an exception in the agent loop.

Tools that change the world outside Themi (send an email, place an order)
are built with `@staged_tool`. Their handler can't act: it returns a
`Proposal`, and the registry stages that through the trust tiers, which run
it at once (Tier 2) or wait for the person's yes (Tier 1). The registry
refuses any side-effect tool built another way, so there's no path around
the tiers.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import jsonschema

from themi.accounts.models import Member
from themi.ai.types import ToolCall, ToolResult, ToolSpec

if TYPE_CHECKING:
    from themi.core.services import Services

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ToolContext:
    member: Member
    services: Services


@dataclass(frozen=True)
class Proposal:
    """What a side-effect tool wants done, for the trust tiers to decide on."""

    category: str
    summary: str
    executor: str
    payload: dict[str, Any] = field(default_factory=dict)


Handler = Callable[[ToolContext, dict[str, Any]], Awaitable[Any]]


class ToolDeclined(Exception):
    """A tool has nothing to do (already done, already waiting...). The message goes
    back to the model as the tool's result; nothing was changed or staged."""


@dataclass(frozen=True)
class Tool:
    spec: ToolSpec
    handler: Handler
    proposes: bool = False  # True for @staged_tool: the handler returns a Proposal


def schema(properties: dict[str, Any]) -> dict[str, Any]:
    """A closed object schema where every property is required (strict-mode friendly)."""
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def tool(name: str, description: str, properties: dict[str, Any]) -> Callable[[Handler], Tool]:
    """A tool that only reads or records things inside Themi."""

    def wrap(handler: Handler) -> Tool:
        return Tool(ToolSpec(name, description, schema(properties)), handler)

    return wrap


def staged_tool(
    name: str, description: str, properties: dict[str, Any]
) -> Callable[[Handler], Tool]:
    """A tool with effects outside Themi. Its handler returns a Proposal."""

    def wrap(handler: Handler) -> Tool:
        spec = ToolSpec(name, description, schema(properties), side_effect=True)
        return Tool(spec, handler, proposes=True)

    return wrap


class ToolRegistry:
    def __init__(self, tools: list[Tool] | None = None) -> None:
        self._tools: dict[str, Tool] = {}
        for t in tools or []:
            self.register(t)

    def register(self, t: Tool) -> None:
        if t.spec.name in self._tools:
            raise ValueError(f"tool {t.spec.name} is already registered")
        if t.spec.side_effect != t.proposes:
            raise ValueError(
                f"tool {t.spec.name}: side-effect tools must be built with @staged_tool "
                "so they go through the trust tiers"
            )
        self._tools[t.spec.name] = t

    def specs(self) -> list[ToolSpec]:
        # Sorted, so the tool list (part of the cached prompt prefix) is stable.
        return [self._tools[name].spec for name in sorted(self._tools)]

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    async def run(self, call: ToolCall, ctx: ToolContext) -> ToolResult:
        t = self._tools.get(call.name)
        if t is None:
            return ToolResult(call.id, f"There's no tool called {call.name}.", is_error=True)
        try:
            jsonschema.validate(call.arguments, t.spec.input_schema)
        except jsonschema.ValidationError as exc:
            return ToolResult(call.id, f"Invalid arguments: {exc.message}", is_error=True)
        try:
            output = await t.handler(ctx, call.arguments)
            if t.proposes:
                output = await self._stage(output, ctx)
            elif not isinstance(output, str):
                raise TypeError(f"tool {call.name} returned {type(output).__name__}, not text")
        except ToolDeclined as exc:
            return ToolResult(call.id, str(exc))
        except Exception as exc:
            log.exception("Tool %s failed for member %s", call.name, ctx.member.id)
            return ToolResult(
                call.id,
                f"The tool failed ({type(exc).__name__}). Nothing was changed.",
                is_error=True,
            )
        log.info("Tool %s ran for member %s", call.name, ctx.member.id)
        return ToolResult(call.id, output)

    @staticmethod
    async def _stage(proposal: Any, ctx: ToolContext) -> str:
        if not isinstance(proposal, Proposal):
            raise TypeError("a staged tool must return a Proposal")
        outcome = await ctx.services.autonomy.stage(
            proposal.category,
            ctx.member,
            proposal.summary,
            proposal.payload,
            proposal.executor,
            interactive=True,  # tools run inside a conversation
        )
        action = outcome.action
        if action.status == "pending":
            return (
                f"Staged for approval (action {action.id}): {proposal.summary}. Nothing happens "
                "until they say yes; don't describe it as done."
            )
        if action.status == "done":
            return f"Done automatically (action {action.id}): {outcome.message}"
        return f"Tried but it failed (action {action.id}); it can be retried: {outcome.message}"


def dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False)
