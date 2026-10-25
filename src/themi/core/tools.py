"""Tools the model can call.

Each tool has a closed JSON Schema (`additionalProperties: false`, every
property required), so Claude can run it in strict mode and local models in
JSON mode get the same contract. Arguments are validated again before the
handler runs; a bad call comes back to the model as an error result, never
an exception in the agent loop.

`side_effect=True` marks tools that change the world outside Themi (send an
email, place an order). From prompt 11 on, those must stage their action
through the trust tiers instead of acting directly.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
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


Handler = Callable[[ToolContext, dict[str, Any]], Awaitable[str]]


@dataclass(frozen=True)
class Tool:
    spec: ToolSpec
    handler: Handler


def schema(properties: dict[str, Any]) -> dict[str, Any]:
    """A closed object schema where every property is required (strict-mode friendly)."""
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def tool(
    name: str, description: str, properties: dict[str, Any], *, side_effect: bool = False
) -> Callable[[Handler], Tool]:
    def wrap(handler: Handler) -> Tool:
        return Tool(ToolSpec(name, description, schema(properties), side_effect), handler)

    return wrap


class ToolRegistry:
    def __init__(self, tools: list[Tool] | None = None) -> None:
        self._tools: dict[str, Tool] = {}
        for t in tools or []:
            self.register(t)

    def register(self, t: Tool) -> None:
        if t.spec.name in self._tools:
            raise ValueError(f"tool {t.spec.name} is already registered")
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
        except Exception as exc:
            log.exception("Tool %s failed for member %s", call.name, ctx.member.id)
            return ToolResult(
                call.id,
                f"The tool failed ({type(exc).__name__}). Nothing was changed.",
                is_error=True,
            )
        log.info("Tool %s ran for member %s", call.name, ctx.member.id)
        return ToolResult(call.id, output)


def dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False)
