"""The first tools: remembering, context repair, noting energy, open items and answering
one in words.

`log_energy_note` records a signal that the energy model (prompt 18) builds on.
"""

from __future__ import annotations

import re
from typing import Any

from themi.core.tools import Tool, ToolContext, ToolFailed, dumps, more_tools, tool

# What the person must have said themselves before the model answers a card for them.
_SAID = {
    "yes": re.compile(
        r"\b(?:yes|yeah|yep|yup|sure|ok|okay|go ahead|do it|let'?s|sounds good|lock it in|"
        r"give it a (?:go|try)|keep it)\b",
        re.IGNORECASE,
    ),
    "no": re.compile(
        r"\b(?:no|nope|nah|drop|skip|don'?t|not interested|leave it|set it aside)\b",
        re.IGNORECASE,
    ),
    "later": re.compile(r"\b(?:later|not now|not yet)\b", re.IGNORECASE),
}
# A forgotten-context report needs them to say Themi forgot or was told before. A question
# about why Themi did something isn't one (idea #8: that pinned a note about an offer).
_FORGOT = re.compile(
    r"\b(?:forg[eo]t\w*|remember\w*|told you|said (?:so|that|this|it)|again|already|"
    r"keep (?:\w+ing)|wrong|not right|isn'?t right|mixed up)\b",
    re.IGNORECASE,
)


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
    "out why it was missed, fixes that, and returns what to tell them. Not for questions "
    "about why Themi did or suggested something: just answer those.",
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
    if not _FORGOT.search(ctx.request_text):
        raise ToolFailed(
            "Not recorded: they didn't say Themi forgot or got something wrong. Just answer "
            "what they asked."
        )
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


@tool(
    "answer_waiting_item",
    "Answer something waiting on this person (an approval card, a rule to lock, a habit to "
    "try) when they answer it in words, like 'yes, let's give that one a try' or 'drop the "
    "water one'. Only when their message this turn says so themselves: never answer for "
    "them. item: its wording from the open items, or enough of it to tell which.",
    {
        "item": {"type": "string"},
        "decision": {"type": "string", "enum": ["yes", "no", "later"]},
    },
)
async def answer_waiting_item(ctx: ToolContext, args: dict[str, Any]) -> str:
    decision = args["decision"]
    if not _SAID[decision].search(ctx.request_text):
        raise ToolFailed(
            f"Not answered: they haven't said {decision} in their message. Ask them, or "
            "point to the card's buttons."
        )
    wanted = args["item"].strip().lower()
    waiting = ctx.services.awaiting(ctx.member)
    matches = [i for i in waiting if wanted and wanted in i.summary.lower()]
    if len(matches) != 1:
        listed = "; ".join(i.summary for i in waiting) or "nothing"
        raise ToolFailed(f"Not answered: say which item exactly. Waiting: {listed}.")
    outcome = await matches[0].resolve(decision)
    return f"Answered {decision}. Result: {outcome}"


@tool(
    "set_phrasing",
    "How this person likes Themi to say things, when they tell you ('just say it plainly', "
    "'softer please', 'questions are fine, never say should'): style plain (say it straight) "
    "or gentle (indirect, low-key), and their own notes in their words (empty keeps them; "
    "'-' clears them). It's theirs only.",
    {
        "style": {"type": "string", "enum": ["plain", "gentle"]},
        "notes": {"type": "string"},
    },
)
async def set_phrasing(ctx: ToolContext, args: dict[str, Any]) -> str:
    notes = args["notes"].strip()
    member = ctx.services.store.update_settings(
        ctx.member,
        ctx.member.id,
        phrasing=args["style"],
        phrasing_notes=("" if notes == "-" else notes) if notes else None,
    )
    saved = f" Notes: {member.phrasing_notes}" if member.phrasing_notes else ""
    return f"Phrasing for {member.name}: {member.phrasing}.{saved}"


STARTER_TOOLS: list[Tool] = [
    remember_fact,
    report_forgotten_context,
    log_energy_note,
    log_energy_level,
    list_open_items,
    answer_waiting_item,
    set_phrasing,
    more_tools,
]
