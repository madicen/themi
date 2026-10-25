"""Zero-effort meals: two low-prep options from what the pantry has, as buttons.

`suggest_meals` asks the model (structured output) for two options, giving
it the pantry with what's close to its use-by date first and staples marked,
and leaving out anything that's run out. The options go to the person as two
buttons; picking one is recorded (prompt 35 builds meal logging on it).
"""

from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any

from themi import clock
from themi.accounts import Member
from themi.ai.errors import AIError
from themi.ai.settings import AITask
from themi.ai.types import CallKind
from themi.channels.events import Button, InboundEvent
from themi.channels.outbox import Priority
from themi.core.pantry import Pantry, PantryItem
from themi.core.services import Services
from themi.core.tools import ToolContext, tool
from themi.localtime import to_local, to_utc_iso

log = logging.getLogger(__name__)

SOON_DAYS = 3  # "use soon" within this many days of its use-by date

SYSTEM = """\
You suggest two zero-effort meals for a tired household: little prep, few
dishes, 20 minutes or less, nothing that needs a shop first. Build them from
the pantry list. Strongly prefer items marked "use soon" (closest first), then
shelf-stable staples. Make the two options different from each other. Titles
are short and plain ("Spinach and egg fried rice"). Steps are one short line.
"""

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "options": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "uses": {"type": "array", "items": {"type": "string"}},
                    "steps": {"type": "string"},
                    "minutes": {"type": "integer"},
                },
                "required": ["title", "uses", "steps", "minutes"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["options"],
    "additionalProperties": False,
}

OFFER_TEXT = "Two easy options, if either appeals:\n1. {first}\n2. {second}"
CHOSEN_TEXT = "{title} it is.\n> {steps}"  # quoted: recipe steps are kept as written
NO_IDEAS_TEXT = "Meal ideas aren't coming through at the moment (the AI couldn't be reached)."


def pantry_lines(items: list[PantryItem], today: date) -> list[str]:
    """The pantry as the model sees it: use-soon items first (soonest first), then staples,
    then the rest. Items that are out are left out."""

    def order(item: PantryItem) -> tuple[int, str, str]:
        if item.expiry is not None and (item.expiry - today).days <= SOON_DAYS:
            return (0, item.expiry.isoformat(), item.name)
        return (1 if item.staple else 2, "", item.name)

    lines = []
    for item in sorted((i for i in items if i.status != "out"), key=order):
        notes = []
        if item.expiry is not None:
            days = (item.expiry - today).days
            if days <= SOON_DAYS:
                when = "today" if days <= 0 else "tomorrow" if days == 1 else f"in {days} days"
                notes.append(f"use soon: by {when}")
            else:
                notes.append(f"use by {item.expiry.isoformat()}")
        if item.staple:
            notes.append("staple")
        if item.status == "low":
            notes.append("running low")
        lines.append(f"- {item.name}" + (f" ({', '.join(notes)})" if notes else ""))
    return lines


def _option(item: dict[str, Any]) -> dict[str, Any] | None:
    title = " ".join(str(item.get("title") or "").split())[:60]
    if not title:
        return None
    return {
        "title": title,
        "uses": [str(u) for u in item.get("uses") or []][:10],
        "steps": " ".join(str(item.get("steps") or "").split())[:300],
        "minutes": int(item.get("minutes") or 0),
    }


class Meals:
    def __init__(self, services: Services, pantry: Pantry) -> None:
        self.services = services
        self.pantry = pantry
        self.db = services.store.db

    def install(self) -> None:
        self.services.meals = self
        self.services.button_handlers["meal"] = self.on_button
        self.services.tools.register(suggest_meals)

    def prompt(self, request: str) -> str:
        family = self.services.store.get_family()
        today = to_local(clock.now(), family.timezone if family else "UTC").date()
        lines = pantry_lines(self.pantry.items(), today)
        asked = f"They asked: {request}\n\n" if request.strip() else ""
        pantry = "\n".join(lines) if lines else "- (nothing recorded yet: suggest from staples)"
        return f"{asked}Today is {today.isoformat()}. The pantry:\n{pantry}"

    async def suggest(self, member: Member, request: str = "") -> list[dict[str, Any]] | None:
        """Ask for two options and send them as buttons. None if the AI isn't available."""
        try:
            response = await self.services.router.client_for(
                member.id, AITask.STRUCTURED_MISC
            ).structured(
                SYSTEM, self.prompt(request), SCHEMA, max_tokens=800, kind=CallKind.INTERACTIVE
            )
        except AIError as exc:
            log.info("Meal ideas unavailable for member %s: %s", member.id, type(exc).__name__)
            return None
        options = [o for o in map(_option, response.data.get("options") or []) if o][:2]
        if len(options) < 2:
            return None
        suggestion_id = self.db.execute(
            "INSERT INTO meal_suggestions (member_id, options, created_at) VALUES (?, ?, ?)",
            (member.id, json.dumps(options), to_utc_iso(clock.now())),
        )
        await self.services.outbox.send(
            member,
            OFFER_TEXT.format(
                first=f"{options[0]['title']} ({options[0]['minutes']} min)",
                second=f"{options[1]['title']} ({options[1]['minutes']} min)",
            ),
            priority=Priority.REPLY,
            kind="meal",
            buttons=[
                Button(o["title"], "meal", {"suggestion": suggestion_id, "choice": n})
                for n, o in enumerate(options)
            ],
        )
        return options

    async def on_button(self, event: InboundEvent) -> None:
        assert event.button is not None
        row = self.db.one(
            "SELECT * FROM meal_suggestions WHERE id = ? AND member_id = ?",
            (int(event.button.payload["suggestion"]), event.member.id),
        )
        if row is None:
            return
        choice = int(event.button.payload["choice"])
        options = json.loads(row["options"])
        if not 0 <= choice < len(options):
            return
        self.db.execute(
            "UPDATE meal_suggestions SET chosen = ?, chosen_at = ? WHERE id = ?",
            (choice, to_utc_iso(clock.now()), row["id"]),
        )
        option = options[choice]
        if event.button.message_id is not None:
            await self.services.outbox.edit(
                event.member,
                event.button.message_id,
                CHOSEN_TEXT.format(title=option["title"], steps=option["steps"]),
            )


@tool(
    "suggest_meals",
    "Offer two zero-effort meal ideas from what's in the pantry, as buttons. Use when someone "
    "asks what to eat or make, or sounds too tired to cook.",
    {
        "request": {
            "type": "string",
            "description": "Anything they said they want (e.g. 'something warm'), or ''.",
        }
    },
)
async def suggest_meals(ctx: ToolContext, args: dict[str, Any]) -> str:
    meals = ctx.services.meals
    assert meals is not None
    options = await meals.suggest(ctx.member, str(args.get("request") or ""))
    if options is None:
        return NO_IDEAS_TEXT
    titles = " / ".join(o["title"] for o in options)
    return (
        f"Sent two options as buttons ({titles}). They're already in the chat, so a short "
        "line is enough; don't list them again."
    )
