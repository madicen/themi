"""Pantry, swaps and wrap-up on the cook screen (CK6).

While gathering, a line whose item the pantry has out or low (said, or predicted from
receipts) is marked "might be out". A tap on it offers [Add to groceries], staged as
`grocery_list_add` through the trust tiers, and [Ask for a swap], a question in the Ask
Themi drawer with the pantry in the context as data.

After [All done], one offer at a time, each once: the warm line (CK5), RC5's save offer for
a recipe from the web, then "Anything used up?" with the session's ingredient items as
chips (each tap does what "used the last olive oil" does: the pantry item is out, and a
staple is staged for the grocery list), then "Want company for cleanup?" [Yes] [Not now].
Yes starts a body double Sprint Partner session, "Clean up after Pancakes" (with the
dishwasher's status line when that module is on), and /session turns to it. Nothing is said
in chat about any of it, and nothing more if they leave the screen.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from themi.accounts import Member
from themi.channels.outbox import Priority
from themi.core import keys
from themi.core.prompts import as_data

if TYPE_CHECKING:
    from themi_home.cooking import Cooking, Session
    from themi_home.recipes import Recipe

log = logging.getLogger(__name__)

LOW = ("out", "low")
USED_TEXT = "Anything used up?"
SAVE_TEXT = "Keep this one in the cookbook?"
CLEANUP_TEXT = "Want company for cleanup?"
SKIP_ITEMS = {"water"}
WRAP_TAPS = ("wrap_save", "wrap_save_no", "wrap_used", "wrap_used_done", "wrap_cleanup",
             "wrap_cleanup_no")  # fmt: skip


def might_be_out(cooking: Cooking, recipe: Recipe) -> set[int]:
    """The ingredient lines whose item the pantry has out or low."""
    pantry = cooking.services.maybe(keys.pantry)
    if pantry is None:
        return set()
    out = set()
    for n, item in enumerate(cooking.groceries.known(recipe)):
        found = pantry.item(item.item)
        if found is not None and found.status in LOW:
            out.add(n)
    return out


def used_items(cooking: Cooking, recipe: Recipe) -> list[str]:
    names: list[str] = []
    for item in cooking.groceries.known(recipe):
        name = item.item.strip()
        if name and name.lower() not in SKIP_ITEMS and name not in names:
            names.append(name)
    return names


def offer(cooking: Cooking, session: Session, recipe: Recipe) -> dict[str, Any] | None:
    """The wrap-up's next offer, or None when each has been made and answered."""
    if session.outcome != "finished":
        return None
    wrap = session.wrap
    if (
        "save" not in wrap
        and recipe.source == "web"
        and cooking.services.maybe(keys.cookbook_save) is not None
    ):
        return {"kind": "save", "text": SAVE_TEXT}
    pantry = cooking.services.maybe(keys.pantry)
    if pantry is not None and not wrap.get("used_done"):
        tapped = set(wrap.get("used", []))
        chips = [{"name": name, "on": name in tapped} for name in used_items(cooking, recipe)]
        if chips:
            return {"kind": "used", "text": USED_TEXT, "chips": chips}
    if "cleanup" not in wrap and cooking.services.maybe(keys.body_double) is not None:
        return {"kind": "cleanup", "text": CLEANUP_TEXT}
    return None


async def tap(
    cooking: Cooking, session: Session, recipe: Recipe, action: str, form: dict[str, Any]
) -> tuple[bool, str]:
    """A wrap-up tap: (done, what the screen says once)."""
    member = cooking._owner(session)
    shown = offer(cooking, session, recipe)
    kind = shown["kind"] if shown else ""
    said = ""
    if action in ("wrap_save", "wrap_save_no") and kind == "save":
        session.wrap["save"] = "yes" if action == "wrap_save" else "no"
        saver = cooking.services.maybe(keys.cookbook_save)
        if action == "wrap_save" and saver is not None:
            try:
                await saver.offer(member, recipe)
                said = "The cookbook entry is in your chat to say yes to."
            except Exception as exc:  # DocsError: no cookbook doc chosen yet
                said = str(exc)
    elif action == "wrap_used" and kind == "used":
        name = str(form.get("name", ""))
        if name not in used_items(cooking, recipe) or name in session.wrap.get("used", []):
            return False, ""
        session.wrap["used"] = [*session.wrap.get("used", []), name]
        said = await used_up(cooking, member, name)
    elif action == "wrap_used_done" and kind == "used":
        session.wrap["used_done"] = True
    elif action in ("wrap_cleanup", "wrap_cleanup_no") and kind == "cleanup":
        session.wrap["cleanup"] = "yes" if action == "wrap_cleanup" else "no"
        if action == "wrap_cleanup":
            cooking.save_wrap(session)
            await cleanup(cooking, member, recipe)
            return True, ""
    else:
        return False, ""
    cooking.save_wrap(session)
    return True, said


async def used_up(cooking: Cooking, member: Member, name: str) -> str:
    """As "used the last olive oil" in chat (`update_pantry`): the item is out, and a
    staple is staged for the grocery list through the tiers."""
    pantry = cooking.services.maybe(keys.pantry)
    if pantry is None:
        return ""
    item = pantry.set_status(name, "out", source="said", by=member)
    if not item.staple:
        return f"{item.name.capitalize()}: out."
    outcome = await pantry.stage_restock(member, [item.name], interactive=True)
    if outcome is None:
        return f"{item.name.capitalize()}: out, and already on the grocery list."
    return f"{item.name.capitalize()}: out. {outcome.message}"


async def to_groceries(cooking: Cooking, member: Member, name: str) -> str:
    """[Add to groceries] on a "might be out" line: staged as `grocery_list_add`."""
    from themi_home.groceries import CATEGORY, EXECUTOR, item_name, list_summary

    groceries = cooking.services.maybe(keys.groceries)
    name = item_name(name)
    if groceries is not None and (
        groceries.is_needed(name) or name in groceries.awaiting_approval()
    ):
        return f"{name.capitalize()} is already on the grocery list."
    outcome = await cooking.services.autonomy.stage(
        CATEGORY, member, list_summary([name]), {"items": [name]}, EXECUTOR, interactive=True
    )
    return outcome.message


def swap_question(name: str, recipe: Recipe) -> str:
    return f"I might be out of {name}. What could I use instead in the {recipe.name}?"


def pantry_data(cooking: Cooking) -> str:
    """The pantry, as data for a swap question."""
    pantry = cooking.services.maybe(keys.pantry)
    if pantry is None:
        return ""
    lines = [f"{p.name}: {p.status}" for p in pantry.items()][:80]
    return as_data("pantry", "\n".join(lines)) if lines else ""


async def cleanup(cooking: Cooking, member: Member, recipe: Recipe) -> None:
    """[Yes] to company for cleanup: a Sprint Partner session, its start in chat (with the
    dishwasher's line), and /session turns to it."""
    from themi_home.body_double import SPRINT

    bd = cooking.services.maybe(keys.body_double)
    if bd is None:
        return
    session, text, buttons = await bd.start(member, mode=SPRINT,
                                            label=f"Clean up after {recipe.name}")  # fmt: skip
    dishwasher = cooking.services.maybe(keys.dishwasher)
    line = dishwasher.status_line() if dishwasher is not None else ""
    if line:
        text = f"{text}\n{line}"
    result = await cooking.services.outbox.send(
        member, text, priority=Priority.REPLY, kind="body_double", buttons=buttons
    )
    if result.outbox_id is not None:
        bd.remember_message(session, cooking.services.outbox.message_id(result.outbox_id))
