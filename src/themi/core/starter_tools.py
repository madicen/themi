"""The first tools: remembering facts, noting energy, listing open items.

`remember_fact` writes to a scratch table that prompt 14 replaces with the
full memory store. `log_energy_note` records a signal that the energy model
(prompt 18) builds on.
"""

from __future__ import annotations

from typing import Any

from themi import clock
from themi.core.tools import Tool, ToolContext, dumps, tool
from themi.localtime import to_utc_iso


@tool(
    "remember_fact",
    "Save something about the household or this person to remember later "
    "(e.g. 'the vet is on Tuesdays', 'Erin prefers oat milk').",
    {
        "subject": {"type": "string", "description": "Short topic, e.g. 'vet' or 'groceries'."},
        "fact": {"type": "string", "description": "The fact itself, in one sentence."},
    },
)
async def remember_fact(ctx: ToolContext, args: dict[str, Any]) -> str:
    subject, fact = args["subject"].strip(), args["fact"].strip()
    if not fact:
        return "Nothing to remember: the fact was empty."
    ctx.services.store.db.execute(
        "INSERT INTO scratch_facts (member_id, subject, fact, created_at) VALUES (?, ?, ?, ?)",
        (ctx.member.id, subject, fact, to_utc_iso(clock.now())),
    )
    return f"Remembered: {fact}"


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


STARTER_TOOLS: list[Tool] = [remember_fact, log_energy_note, list_open_items]
