"""The wrap-up's notes (CF5): after [All done], before CK6's offers, one note at a time.

Each shows the note as it was left (and who left it, on a group session), then what Themi
proposes: the step or line before and after, the changed words marked. A change offers
[Change the recipe] [Keep as a note] [Not now]; a note to keep, [Keep as a note] [Not
now]; a display fix already made, "Fixed on Themi's side, and reported" with [OK] [Undo];
a wrong gram weight, [Fix the weights guide] [Not now]. Only the person whose session it
was decides (the plan's decision 7): a partner sees the offer without its buttons.

On the cook screen these are wrap-up offers like CK6's. Cooked in chat with no screen open,
the same offers go to chat one at a time, as messages with buttons. Nothing is said about
notes left waiting.
"""

from __future__ import annotations

import difflib
import json
import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

from themi.accounts import Member
from themi.channels.events import Button, InboundEvent
from themi.channels.outbox import Priority
from themi_home.cookbook_edit import Op, Rejected

if TYPE_CHECKING:
    from themi_home.cooking import Cooking, Session
    from themi_home.cooking_notes import CookingNotes, Note
    from themi_home.recipes import Recipe

log = logging.getLogger(__name__)

TO_DECIDE = ("open", "fixed")
NOTE_TAPS = ("wrap_note_change", "wrap_note_keep", "wrap_note_later", "wrap_note_ok",
             "wrap_note_undo", "wrap_note_grams")  # fmt: skip
BUTTON_KIND = "cooking_note"
FIXED_TEXT = "Fixed on Themi's side, and reported."
CHANGED_ELSEWHERE = "That changed in the recipe since, so it's kept on the recipe's page."
ASK_IN_CHAT = "It's in your chat to say yes to."


def to_decide(notes: CookingNotes, session: Session) -> list[Note]:
    return [n for n in notes.for_session(session.id) if n.status in TO_DECIDE
            and n.kind != "other"]  # fmt: skip


def marked(before: str, after: str) -> list[dict[str, Any]]:
    """The after words, with those not in the before marked: [{"text", "new"}]."""
    old, new = before.split(), after.split()
    out: list[dict[str, Any]] = []
    for tag, _, _, j1, j2 in difflib.SequenceMatcher(a=old, b=new, autojunk=False).get_opcodes():
        if j1 == j2:
            continue
        words = " ".join(new[j1:j2])
        changed = tag != "equal"
        if out and out[-1]["new"] == changed:
            out[-1]["text"] += " " + words
        else:
            out.append({"text": words, "new": changed})
    return out


def preview(note: Note, recipe: Recipe) -> list[dict[str, Any]]:
    """Each op as before and after: [{"what", "before": [words], "after": [[segments]]}]."""
    out: list[dict[str, Any]] = []
    steps = [s.text for s in recipe.steps]
    for data in note.proposal.get("ops") or []:
        o = Op.from_json(data)
        if o.op.endswith("_step"):
            n = steps.index(o.old) + 1 if o.old in steps else (
                steps.index(o.olds[0]) + 1 if o.olds and o.olds[0] in steps else 0)  # fmt: skip
            what = f"Step {n}" if n else "A new step"
        elif o.op.endswith("_line"):
            what = "Ingredient"
        else:
            what = "Note on the recipe"
        before = list(o.olds) or ([o.old] if o.old else [])
        joined = " ".join(before)
        after = [marked(joined, t) for t in o.new]
        out.append({"what": what, "before": before, "after": after, "op": o.op})
    return out


def offer(cooking: Cooking, session: Session, recipe: Recipe) -> dict[str, Any] | None:
    """The next note to decide at wrap-up, or None."""
    notes = cooking.notes
    if notes is None:
        return None
    waiting = to_decide(notes, session)
    if not waiting:
        return None
    note = waiting[0]
    who = ""
    if session.in_group and note.member_id != session.member_id:
        who = cooking.services.store.get_member(note.member_id).name
    return {**describe(note, recipe), "who": who, "left": len(waiting)}


def describe(note: Note, recipe: Recipe) -> dict[str, Any]:
    """A note's offer: the note, what Themi proposes, and which buttons."""
    shown: dict[str, Any] = {"kind": "note", "note": note.id, "said": note.words, "who": "",
                             "step": note.step_label}  # fmt: skip
    grams = note.proposal.get("grams")
    if note.status == "fixed":
        shown.update(choice="fixed", text=FIXED_TEXT, summary=note.summary)
    elif grams:
        shown.update(choice="grams", text=grams_text(grams))
    elif note.kind == "change" and note.status != "stale":  # stale: the words moved on
        shown.update(choice="change", text="Make this change to the recipe?",
                     changes=preview(note, recipe))  # fmt: skip
    else:
        shown.update(choice="note", text="Keep this as a note on the recipe?",
                     changes=preview(note, recipe))  # fmt: skip
    return shown


def decider(cooking: Cooking, note: Note) -> int:
    """Who decides a note: the person whose session it was (decision 7), else who left it."""
    session = cooking.get(note.session_id) if note.session_id else None
    return session.member_id if session is not None else note.member_id


def grams_text(grams: dict[str, Any]) -> str:
    unit = grams.get("unit") or ""
    return (f"Fix the weights guide: {grams['amount']:g} {unit} {grams['ingredient']} is "
            f"{grams['grams']:g} g?").replace("  ", " ")  # fmt: skip


async def tap(
    cooking: Cooking, session: Session, member: Member, action: str, form: dict[str, Any]
) -> tuple[bool, str]:
    """A tap on a note's offer: (done, what the screen says once). Only the owner decides."""
    notes = cooking.notes
    recipe = cooking.recipes.get(session.recipe_id)
    if notes is None or recipe is None or member.id != session.member_id:
        return False, ""
    shown = offer(cooking, session, recipe)
    if shown is None or str(form.get("note", "")) != str(shown["note"]):
        return False, ""
    note = notes.get(int(shown["note"]))
    assert note is not None
    said = await decide(notes, note, member, action)
    cooking._bump(session)
    return True, said


async def decide(notes: CookingNotes, note: Note, member: Member, action: str) -> str:
    """What a decision does, on the cook screen, the recipe's page (CF6) or in chat."""
    edits = notes.edits
    if action == "wrap_note_later":
        notes._set(note, status="waiting")
        return ""
    if action == "wrap_note_ok":
        notes._set(note, status="ok")
        return ""
    if action == "wrap_note_undo":
        if note.fix_id is not None:
            notes.undo_fix(note)
        return "Put back as it was shown."
    if action == "wrap_note_grams":
        return await fix_grams(notes, note, member)
    if action in ("wrap_note_change", "wrap_note_keep") and edits is not None:
        try:
            outcome = await edits.stage(member, note, as_note=action == "wrap_note_keep")
        except Rejected as exc:
            log.info("Note %s no longer fits its recipe (%s)", note.id, exc)
            notes._set(note, status="waiting")
            return CHANGED_ELSEWHERE
        if outcome.action.status == "pending":
            notes._set(note, status="staged")
            return ASK_IN_CHAT
        return outcome.message
    return ""


async def fix_grams(notes: CookingNotes, note: Note, member: Member) -> str:
    """GW5's correction, as "that's wrong, it's 2.5 g" in chat would make it."""
    from themi_home.gram_weights import GramWeights

    weights = notes.services.maybe(GramWeights)
    grams = note.proposal.get("grams") or {}
    if weights is None or not grams:
        notes._set(note, status="waiting")
        return ""
    asked = weights.check(float(grams["amount"]), str(grams["unit"]), float(grams["grams"]))
    if asked is not None:  # a weight that looks off: left for chat, where it can be asked
        notes._set(note, status="waiting")
        return asked[0]
    said, _ = await weights.correct(member, str(grams["ingredient"]), float(grams["amount"]),
                                    str(grams["unit"]), float(grams["grams"]))  # fmt: skip
    notes._set(note, status="done")
    return said


# ----- in chat, when the wrap-up isn't on a screen -------------------------------------------


def chat_text(shown: dict[str, Any]) -> tuple[str, list[Button]]:
    """A note's offer as a chat message with buttons."""
    lines = [f'Your note{" from " + shown["who"] if shown["who"] else ""}: "{shown["said"]}"']
    for change in shown.get("changes") or []:
        for before in change["before"]:
            lines.append(f"{change['what']} was:\n> {before}")
        for after in change["after"]:
            lines.append("Now:\n> " + " ".join(seg["text"] for seg in after))
    lines.append(shown["text"])
    note = shown["note"]

    def b(label: str, action: str) -> Button:
        return Button(label, BUTTON_KIND, {"action": action, "note": note})

    buttons = {
        "change": [b("Change the recipe", "wrap_note_change"),
                   b("Keep as a note", "wrap_note_keep"), b("Not now", "wrap_note_later")],
        "note": [b("Keep as a note", "wrap_note_keep"), b("Not now", "wrap_note_later")],
        "fixed": [b("OK", "wrap_note_ok"), b("Undo", "wrap_note_undo")],
        "grams": [b("Fix the weights guide", "wrap_note_grams"), b("Not now", "wrap_note_later")],
    }[shown["choice"]]  # fmt: skip
    return "\n".join(lines), buttons


async def next_in_chat(cooking: Cooking, session: Session) -> bool:
    """The next note's offer in chat, for a wrap-up with no screen open. False when none."""
    recipe = cooking.recipes.get(session.recipe_id)
    shown = offer(cooking, session, recipe) if recipe is not None else None
    if shown is None:
        return False
    text, buttons = chat_text(shown)
    await cooking.services.outbox.send(cooking._owner(session), text, priority=Priority.REPLY,
                                       kind="cooking", buttons=buttons)  # fmt: skip
    return True


async def on_button(cooking: Cooking, event: InboundEvent) -> None:
    assert event.button is not None
    notes = cooking.notes
    payload = event.button.payload
    note = notes.get(int(payload.get("note", 0))) if notes is not None else None
    if notes is None or note is None or note.status not in TO_DECIDE:
        return
    member = cooking.services.store.get_member(event.member.id)
    session = cooking.get(note.session_id) if note.session_id else None
    owner = session.member_id if session is not None else note.member_id
    if member.id != owner:
        return
    said = await decide(notes, note, member, str(payload.get("action", "")))
    if event.button.message_id is not None:
        done = {"wrap_note_later": "Kept on the recipe's page for later.",
                "wrap_note_ok": "OK."}.get(str(payload.get("action")), said or "Done.")  # fmt: skip
        await cooking.services.outbox.edit(member, event.button.message_id, done)
    if session is not None:
        await next_in_chat(cooking, session)


# ----- CF6: the recipe's page, and "From last time" ----------------------------------------

PAGE_STATUSES = ("open", "fixed", "waiting", "stale")
LAST_TIME = ("open", "waiting")


def page_notes(cooking: Cooking, recipe: Recipe, viewer: Member) -> list[dict[str, Any]]:
    """The notes still to decide, oldest first, each with its buttons for whoever decides."""
    from themi.localtime import to_local

    notes = cooking.notes
    if notes is None:
        return []
    out = []
    for note in notes.for_recipe(recipe.id, PAGE_STATUSES):
        if note.kind in (None, "other"):
            continue
        when = to_local(datetime.fromisoformat(note.created_at), cooking._tz())
        out.append({
            **describe(note, recipe),
            "who": cooking.services.store.get_member(note.member_id).name,
            "when": f"{when:%b} {when.day}",
            "can_decide": viewer.id == decider(cooking, note),
        })  # fmt: skip
    return out


def page_history(cooking: Cooking, recipe: Recipe) -> list[dict[str, Any]]:
    """The changes made from notes, newest first; [Undo] while Themi's copy still has the
    words they wrote (the doc is checked again when it's tapped)."""
    from themi.localtime import to_local
    from themi_home.cookbook_edit import apply, shape_of, undo_ops

    out = []
    for row in cooking.db.query(
        "SELECT * FROM cookbook_edits WHERE recipe_id = ? AND undo_of IS NULL ORDER BY id DESC",
        (recipe.id,),
    ):
        ops = [Op.from_json(o) for o in json.loads(row["ops"])]
        try:
            apply(undo_ops(ops), shape_of(recipe))
            can_undo = not row["undone_at"]
        except Rejected:
            can_undo = False
        when = to_local(datetime.fromisoformat(row["written_at"]), cooking._tz())
        words = "Added a note" if all(o.op == "add_note" for o in ops) else "Changed"
        out.append({"id": row["id"], "what": row["summary"] or words, "words": words,
                    "when": f"{when:%b} {when.day}", "undone": bool(row["undone_at"]),
                    "can_undo": can_undo})  # fmt: skip
    return out


def last_time(
    cooking: Cooking, session: Session, recipe: Recipe, text: str, index: int
) -> list[str]:
    """CF6: notes still waiting from an earlier cook, on the step shown: matched by its
    words while the recipe still has them, else by the step's place."""
    from themi_home.cooking import step_parts

    notes = cooking.notes
    if notes is None:
        return []
    texts = {p.text for p in step_parts(recipe)}
    found = []
    for note in notes.for_recipe(session.recipe_id, LAST_TIME):
        if note.session_id == session.id or note.kind in (None, "other") or not note.step_text:
            continue
        here = note.step_text == text if note.step_text in texts else note.step_index == index
        if here:
            found.append(note.words)
    return found
