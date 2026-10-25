"""The first tools: remembering, context repair, noting energy, listing open items.

`log_energy_note` records a signal that the energy model (prompt 18) builds on.
"""

from __future__ import annotations

from typing import Any

from themi import clock
from themi.core.tools import Tool, ToolContext, dumps, tool
from themi.localtime import to_utc_iso


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
    if not ctx.member.tracks("text_notes"):
        return "This person has turned off energy notes; nothing was recorded."
    ctx.services.store.db.execute(
        "INSERT INTO energy_signals (member_id, source, value, note, created_at) "
        "VALUES (?, 'text_note', ?, ?, ?)",
        (ctx.member.id, float(args["effect"]), args["note"][:200], to_utc_iso(clock.now())),
    )
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
    list_open_items,
]
