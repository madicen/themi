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
import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
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
    request_text: str = ""  # what the person wrote this turn, for "did they ask for it?"
    previous_text: str = ""  # their message before it, for a follow-up like "and limes"
    said_before: str = ""  # Themi's last message to them, for an answer like "Yes please"
    # Each tool call this turn: "ok", "declined" (nothing to do) or "failed".
    outcomes: list[str] = field(default_factory=list)
    # A tool sent the answer itself, word for word (a day summary): the model's reply is
    # kept only as a short line (bug #89: it wrote the day out again).
    answered: list[str] = field(default_factory=list)
    # The tool groups this turn sends (P1); `more_tools` adds to it.
    groups: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class Proposal:
    """What a side-effect tool wants done, for the trust tiers to decide on."""

    category: str
    summary: str
    executor: str
    payload: dict[str, Any] = field(default_factory=dict)
    # The person asked for exactly this in their own words (checked by the tool against
    # what they wrote, never the model's say-so). The trust tiers decide what that allows.
    requested: bool = False
    expires: datetime | None = None  # no use after then: an unanswered card lapses (#64)


Handler = Callable[[ToolContext, dict[str, Any]], Awaitable[Any]]


class ToolFailed(Exception):
    """A tool couldn't do what was asked (no such task, not theirs...). The message goes
    back to the model as an error result, and the turn knows nothing was done."""


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


# ----- which tools a message gets (P1) ---------------------------------------------------
#
# Every message sent all the tools' schemas, about 8,000 tokens (bug #29). A core set always
# goes; the rest go by group when the message or the last few messages call for them, and
# `more_tools` adds a group mid-turn. A tool not in TOOL_GROUPS is core, so a new tool is
# never hidden by accident.

GROUPS: dict[str, tuple[str, str]] = {  # name: (what it's for, words that call for it)
    "schedules": (
        "repeating chores, plans, importance, check-in reviews",
        r"every|each|daily|weekly|monthly|repeat|schedule|plan|miles|km|minutes|weeks?|"
        r"twice|once a|important|urgent|priority|check.?in|sunset|routine|always|remind|"
        r"(?:mon|tues|wednes|thurs|fri|satur|sun)days|evenings|mornings|nights|weekends",
    ),
    "calendar": (
        "calendar events, day summaries, drive times, blocking time",
        r"calendar|appointment|meeting|event|today|tomorrow|tonight|"
        r"(?:morning|afternoon|evening)(?!s?\s+routines?)|day look|what'?s on|monday|"
        r"tuesday|wednesday|thursday|friday|saturday|sunday|weekend|drive|leave|traffic|"
        r"block|time for|find (?:me )?time|summary",
    ),
    "lists": (
        "named lists, the wall's lists, usual stores",
        r"list|packing|ideas|tick|cross|check off|clear|things to cook|store|amazon|"
        r"target|costco|home depot",
    ),
    "wall": (
        "the Cozyla wall: chore chart, routines, to-do lists",
        r"wall|cozyla|chart|chore|routine",
    ),
    "email": (
        "inboxes, expected emails, time-sensitive and important senders, the email audit",
        r"e-?mail|inbox|gmail|sender|expect|bill|statement|confirmation|unsubscribe|audit|"
        r"time.sensitive|archive|noise|junk|spam|mark(?:ed)? (?:as )?read",
    ),
    "pantry": (
        "the pantry and meal ideas",
        r"pantry|fridge|freezer|meal|dinner|lunch|breakfast|cook|recipe|out of|low on|"
        r"running low|ran out|leftover|used (?:up|the last)|last of|finished the|picked up|"
        r"bought|got (?:some|more)|stocked|use (?:it |them )?up|using up|expir|go(?:es)? off|"
        r"went off",
    ),
    "calls": ("phone calls to make for them", r"call|phone|ring|vendor|script"),
    "spending": (
        "money spent: takeout, eating out, business expenses",
        r"spent|spend|paid|\$|expense|budget|takeout|take-out|doordash|door dash|uber eats|"
        r"eating out|ate out|restaurant|receipt|cost",
    ),
    "settings": (
        "pausing messages, breaks, phrasing, quiet hours",
        r"pause|mute|quiet|stop (?:sending|messaging)|resume|phrasing|wording|tone|gentle|"
        r"plain|pushy|too many|limit|break\b|\brest\b|i'?m back",
    ),
}
TOOL_GROUPS: dict[str, str] = {
    **dict.fromkeys(("start_break", "end_break"), "settings"),
    **dict.fromkeys(
        ("log_spending", "spending_summary", "mark_business_expense", "remove_spending"),
        "spending",
    ),
    **dict.fromkeys(
        (
            "set_task_schedule",
            "set_task_plan",
            "set_task_importance",
            "set_check_in_reviews",
            "set_task_medicine",
        ),
        "schedules",
    ),
    **dict.fromkeys(
        (
            "add_calendar_event",
            "move_calendar_event",
            "delete_calendar_event",
            "day_summary",
            "drive_time",
            "block_time_for_task",
            "find_time_for_task",
        ),
        "calendar",
    ),
    **dict.fromkeys(
        (
            "create_list",
            "add_to_list",
            "tick_list_items",
            "remove_from_list",
            "show_lists",
            "delete_list",
            "put_list_on_wall",
            "set_usual_store",
        ),
        "lists",
    ),
    **dict.fromkeys(
        (
            "put_task_on_wall_list",
            "put_task_on_chore_chart",
            "set_chore_chart_limit",
            "change_chore_chart",
            "add_to_wall_routine",
            "show_routine",
        ),
        "wall",
    ),
    **dict.fromkeys(
        (
            "expect_email",
            "list_expected_emails",
            "forget_expected_email",
            "set_urgent_senders",
            "set_inbox_watched",
            "inbox_setup",
            "keep_email",
            "start_email_audit",
            "set_sender_levels",
            "archive_noise_emails",
        ),
        "email",
    ),
    **dict.fromkeys(("update_pantry", "show_pantry", "suggest_meals"), "pantry"),
    **dict.fromkeys(("draft_vendor_call", "log_call_outcome"), "calls"),
    **dict.fromkeys(("pause_messages", "resume_messages", "set_phrasing"), "settings"),
}
_GROUP_WORDS = {
    name: re.compile(rf"\b(?:{words})", re.IGNORECASE) for name, (_, words) in GROUPS.items()
}


def choose_groups(texts: Sequence[str]) -> set[str]:
    """The groups these messages call for (this one and the last few)."""
    joined = " ".join(texts)
    return {name for name, pattern in _GROUP_WORDS.items() if pattern.search(joined)}


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

    def specs(self, groups: set[str] | None = None) -> list[ToolSpec]:
        """Every tool, or (P1) the core and these groups'. Sorted, so the tool list (part
        of the cached prompt prefix) is stable."""
        return [
            self._tools[name].spec
            for name in sorted(self._tools)
            if groups is None or TOOL_GROUPS.get(name, "core") in groups | {"core"}
        ]

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    async def run(self, call: ToolCall, ctx: ToolContext) -> ToolResult:
        t = self._tools.get(call.name)
        if t is None:
            return ToolResult(call.id, f"There's no tool called {call.name}.", is_error=True)
        result, outcome = await self._run(t, call, ctx)
        ctx.outcomes.append(outcome)
        return result

    async def _run(self, t: Tool, call: ToolCall, ctx: ToolContext) -> tuple[ToolResult, str]:
        call = replace(call, arguments=_as_typed(call.arguments, t.spec.input_schema))
        try:
            jsonschema.validate(call.arguments, t.spec.input_schema)
        except jsonschema.ValidationError as exc:
            return ToolResult(call.id, f"Invalid arguments: {exc.message}", is_error=True), "failed"
        try:
            output = await t.handler(ctx, call.arguments)
            if t.proposes:
                output = await self._stage(output, ctx)
            elif not isinstance(output, str):
                raise TypeError(f"tool {call.name} returned {type(output).__name__}, not text")
        except ToolDeclined as exc:
            return ToolResult(call.id, str(exc)), "declined"
        except ToolFailed as exc:
            return ToolResult(call.id, f"{exc} Nothing was changed.", is_error=True), "failed"
        except Exception as exc:
            log.exception("Tool %s failed for member %s", call.name, ctx.member.id)
            failure = f"The tool failed ({type(exc).__name__}). Nothing was changed."
            return ToolResult(call.id, failure, is_error=True), "failed"
        log.info("Tool %s ran for member %s", call.name, ctx.member.id)
        return ToolResult(call.id, output), "ok"

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
            requested=proposal.requested,
            expires=proposal.expires,
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


_INTEGER = re.compile(r"[+-]?\d+")
_NUMBER = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)")


def _as_typed(value: Any, schema: dict[str, Any]) -> Any:
    """Numbers and true/false that came as text, as the schema's type (eval energy-plumber:
    Gemini sent log_energy_note's effect as "-3"; its function schemas take only text
    choices). Anything else is left for the schema check to refuse."""
    kind = schema.get("type")
    if kind == "object" and isinstance(value, dict):
        props = schema.get("properties", {})
        return {k: _as_typed(v, props[k]) if k in props else v for k, v in value.items()}
    if kind == "array" and isinstance(value, list) and "items" in schema:
        return [_as_typed(v, schema["items"]) for v in value]
    if not isinstance(value, str):
        return value
    text = value.strip()
    if kind == "integer" and _INTEGER.fullmatch(text):
        return int(text)
    if kind == "number" and _NUMBER.fullmatch(text):
        return float(text)
    if kind == "boolean" and text.lower() in ("true", "false"):
        return text.lower() == "true"
    return value


def dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False)


@tool(
    "more_tools",
    "Bring in more of Themi's tools for this conversation, when what they ask needs ones "
    "you don't have yet. groups: "
    + "; ".join(f"'{name}' ({what})" for name, (what, _) in GROUPS.items())
    + ".",
    {"groups": {"type": "array", "items": {"type": "string", "enum": list(GROUPS)}}},
)
async def more_tools(ctx: ToolContext, args: dict[str, Any]) -> str:
    added = [g for g in args["groups"] if g in GROUPS and g not in ctx.groups]
    ctx.groups.update(added)
    if not added:
        return "Those tools are here already."
    return f"Added the {', '.join(added)} tools; use them now."
