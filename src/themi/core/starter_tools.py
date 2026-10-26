"""The first tools: remembering, context repair, noting energy, listing open items.

`log_energy_note` records a signal that the energy model (prompt 18) builds on.
"""

from __future__ import annotations

from typing import Any

from themi.core.tools import Tool, ToolContext, dumps, tool


@tool(
    "remember_fact",
    "Save something worth remembering (e.g. 'the vet is on Tuesdays', 'Erin prefers oat "
    "milk'). Household facts are shared with the family; personal ones stay in this "
    "person's conversations.",
    {
        "subject": {"type": "string", "description": "Short topic, e.g. 'vet' or 'groceries'."},
        "fact": {"type": "string", "description": "The fact itself, in one sentence."},
        "about": {
            "type": "string",
            "enum": ["household", "personal"],
            "description": "household for shared facts; personal for things only about them.",
        },
    },
)
async def remember_fact(ctx: ToolContext, args: dict[str, Any]) -> str:
    memory = ctx.services.memory
    assert memory is not None
    fact = args["fact"].strip()
    if not fact:
        return "Nothing to remember: the fact was empty."
    scope = "member" if args["about"] == "personal" else "family"
    saved = memory.remember(ctx.member, args["subject"], fact, scope=scope)
    return f"Remembered: {saved.fact}"


@tool(
    "report_forgotten_context",
    "Use when the person says you forgot, keep forgetting, or got something wrong that "
    "they'd told you before ('you keep forgetting the cat's vet is on Tuesdays'). It works "
    "out why it was missed, fixes that, and returns what to tell them.",
    {
        "what_was_forgotten": {
            "type": "string",
            "description": "The thing that was forgotten, as they put it.",
        },
        "correct_version": {
            "type": "string",
            "description": "What's actually true, as one clear sentence (empty if unclear).",
        },
    },
)
async def report_forgotten_context(ctx: ToolContext, args: dict[str, Any]) -> str:
    memory = ctx.services.memory
    assert memory is not None
    repair = memory.repair(ctx.member, args["what_was_forgotten"], args["correct_version"])
    return f"Diagnosis: {repair.diagnosis}. Tell them, in your own words: {repair.message}"


@tool(
    "log_energy_note",
    "Record how a remark suggests this person's energy is doing, when they mention it "
    "(e.g. 'that call took a lot out of me' is draining; 'had a great nap' is restoring). "
    "Use only when they talk about their own energy or effort.",
    {
        "effect": {
            "type": "integer",
            "enum": [-3, -2, -1, 1, 2, 3],
            "description": "-3 very draining ... -1 a little draining; 1 a little restoring "
            "... 3 very restoring.",
        },
        "note": {"type": "string", "description": "A few words on what they said."},
    },
)
async def log_energy_note(ctx: ToolContext, args: dict[str, Any]) -> str:
    if not ctx.services.energy.record(ctx.member, "text_note", float(args["effect"]), args["note"]):
        return "This person has turned off energy notes; nothing was recorded."
    return "Noted."


@tool(
    "log_energy_level",
    "Record the energy level someone says their day is at ('it's a medium energy day', "
    "'having a high energy day', 'low energy today'). It shapes today only. Use it alongside "
    "anything else they asked for.",
    {
        "level": {"type": "string", "enum": ["low", "medium", "high"]},
        "note": {"type": "string", "description": "A few words on what they said."},
    },
)
async def log_energy_level(ctx: ToolContext, args: dict[str, Any]) -> str:
    value = {"low": -1.0, "medium": 0.0, "high": 1.0}[args["level"]]
    if not ctx.services.energy.record(ctx.member, "day_level", value, args["note"]):
        return "This person has turned off energy notes; nothing was recorded."
    return "Noted."


@tool(
    "list_open_items",
    "List what's currently waiting for this person: approvals, scheduled messages and "
    "other open items.",
    {},
)
async def list_open_items(ctx: ToolContext, args: dict[str, Any]) -> str:
    items = [i.summary for i in ctx.services.open_items(ctx.member)]
    return dumps({"open_items": items}) if items else "Nothing is waiting right now."


STARTER_TOOLS: list[Tool] = [
    remember_fact,
    report_forgotten_context,
    log_energy_note,
    log_energy_level,
    list_open_items,
]
