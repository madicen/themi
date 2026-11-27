"""Changes to a recipe from a cooking note (CF3 checks them, CF4 writes them).

A change is a short list of ops, each anchored on the recipe's own words, never on a number
alone: `replace_step` (old, new), `split_step` (old, two or more new), `merge_steps` (olds,
new), `insert_step` (after, new), `remove_step` (old), `replace_line`, `insert_line` (after,
new, group), `remove_line`, `add_note` (new) and `remove_note` (old). An op whose old words
aren't the recipe's is refused (`Rejected`), so a proposal can't say what the recipe never
said. `apply` gives the recipe as it would be; `inverse` gives the ops that put it back.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from themi_home.cookbook import Line

STEP_OPS = ("replace_step", "split_step", "merge_steps", "insert_step", "remove_step")
LINE_OPS = ("replace_line", "insert_line", "remove_line")
NOTE_OPS = ("add_note", "remove_note")
OPS = (*STEP_OPS, *LINE_OPS, *NOTE_OPS)
log = logging.getLogger(__name__)

MAX_TEXT = 1200
MAX_OPS = 8


class Rejected(ValueError):
    """An op that doesn't fit the recipe as it is."""


def clean(text: str) -> str:
    return " ".join(str(text or "").split())


def note_text(words: str, when: datetime) -> str:
    """A note as the doc keeps it: "Note: less salt (cooked Nov 27)", which the parser
    reads as a note."""
    words = clean(words).rstrip(".")
    return f"Note: {words[:1].upper()}{words[1:]} (cooked {when:%b} {when.day})"


@dataclass(frozen=True)
class Op:
    op: str
    old: str = ""
    olds: tuple[str, ...] = ()
    new: tuple[str, ...] = ()
    after: str = ""
    group: str = ""

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Op:
        op = str(data.get("op") or "")
        if op not in OPS:
            raise Rejected(f"no op called {op!r}")
        return cls(
            op,
            clean(data.get("old", "")),
            tuple(clean(t) for t in data.get("olds") or [] if clean(t)),
            tuple(clean(t)[:MAX_TEXT] for t in data.get("new") or [] if clean(t)),
            clean(data.get("after", "")),
            clean(data.get("group", "")),
        )

    def to_json(self) -> dict[str, Any]:
        return {"op": self.op, "old": self.old, "olds": list(self.olds), "new": list(self.new),
                "after": self.after, "group": self.group}  # fmt: skip

    def inverse(self) -> Op:
        """The op that undoes this one, once it's been applied (`apply` fills `after` and
        `group` in for the removes)."""
        o = self
        match o.op:
            case "replace_step":
                return Op("replace_step", o.new[0], new=(o.old,))
            case "split_step":
                return Op("merge_steps", olds=o.new, new=(o.old,))
            case "merge_steps":
                return Op("split_step", o.new[0], new=o.olds)
            case "insert_step":
                return Op("remove_step", o.new[0], after=o.after)
            case "remove_step":
                return Op("insert_step", new=(o.old,), after=o.after, group=o.group)
            case "replace_line":
                return Op("replace_line", o.new[0], new=(o.old,))
            case "insert_line":
                return Op("remove_line", o.new[0], after=o.after, group=o.group)
            case "remove_line":
                return Op("insert_line", new=(o.old,), after=o.after, group=o.group)
            case "add_note":
                return Op("remove_note", o.new[0])
            case _:  # remove_note
                return Op("add_note", new=(o.old,))


@dataclass
class Shape:
    """A recipe's words, as ops change them."""

    ingredients: list[Line] = field(default_factory=list)
    steps: list[Line] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _find(lines: list[Line], text: str, what: str) -> int:
    for n, line in enumerate(lines):
        if clean(line.text) == text:
            return n
    raise Rejected(f"no {what} says {text!r}")


def _after(lines: list[Line], at: int) -> str:
    return clean(lines[at - 1].text) if at > 0 else ""


def apply(ops: list[Op], shape: Shape) -> tuple[Shape, list[Op]]:
    """The recipe with the ops applied in order, and the ops as applied (each remove with
    the words it followed and its group, so it can be put back). Raises `Rejected`."""
    if not ops or len(ops) > MAX_OPS:
        raise Rejected("no ops, or too many")
    ing, steps, notes = list(shape.ingredients), list(shape.steps), list(shape.notes)
    done: list[Op] = []
    for o in ops:
        need_new = {"split_step": 2}.get(o.op, 0 if o.op in ("remove_step", "remove_line",
                                                             "remove_note") else 1)  # fmt: skip
        if len(o.new) < need_new or (o.op not in ("split_step",) and len(o.new) > 1):
            raise Rejected(f"{o.op} with {len(o.new)} new")
        first = next(iter(o.new), "")
        match o.op:
            case "replace_step" | "split_step":
                at = _find(steps, o.old, "step")
                group = steps[at].group
                steps[at : at + 1] = [Line(t, group) for t in o.new]
                done.append(o)
            case "merge_steps":
                if len(o.olds) < 2:
                    raise Rejected("merge_steps needs two steps or more")
                at = _find(steps, o.olds[0], "step")
                if [clean(s.text) for s in steps[at : at + len(o.olds)]] != list(o.olds):
                    raise Rejected("the steps to merge aren't one after another")
                steps[at : at + len(o.olds)] = [Line(first, steps[at].group)]
                done.append(o)
            case "insert_step":
                at = 0 if not o.after else _find(steps, o.after, "step") + 1
                group = o.group or (steps[at - 1].group if at > 0 else "")
                steps.insert(at, Line(first, group))
                done.append(Op(o.op, new=o.new, after=_after(steps, at), group=group))
            case "remove_step":
                at = _find(steps, o.old, "step")
                gone = steps.pop(at)
                done.append(Op(o.op, o.old, after=_after(steps, at), group=gone.group))
            case "replace_line":
                at = _find(ing, o.old, "ingredient line")
                ing[at] = Line(first, ing[at].group)
                done.append(o)
            case "insert_line":
                if o.after:
                    at = _find(ing, o.after, "ingredient line") + 1
                    group = o.group or ing[at - 1].group
                else:  # at the end of its group, or of the list
                    group = o.group
                    tail = [n for n, line in enumerate(ing) if line.group == group]
                    at = tail[-1] + 1 if tail else len(ing)
                ing.insert(at, Line(first, group))
                done.append(Op(o.op, new=o.new, after=_after(ing, at), group=group))
            case "remove_line":
                at = _find(ing, o.old, "ingredient line")
                gone = ing.pop(at)
                done.append(Op(o.op, o.old, after=_after(ing, at), group=gone.group))
            case "add_note":
                notes.append(first)
                done.append(o)
            case "remove_note":
                if o.old not in [clean(n) for n in notes]:
                    raise Rejected(f"no note says {o.old!r}")
                notes = [n for n in notes if clean(n) != o.old]
                done.append(o)
    return Shape(ing, steps, notes), done


def undo_ops(ops: list[Op]) -> list[Op]:
    return [o.inverse() for o in reversed(ops)]


def shape_of(recipe: Any) -> Shape:
    return Shape(list(recipe.ingredients), list(recipe.steps), list(recipe.notes))


# ----- CF4: writing a change into the doc -------------------------------------------------


@dataclass
class Para:
    """One paragraph of an entry, as the ops change it: an original one (its block, and
    where the next one starts) or a new one."""

    role: str  # "line", "step", "note" or "other" (headings, Source:, the separator)
    body: str  # its words as the recipe reads them (numbering taken off a step)
    group: str = ""
    start: int | None = None  # an original paragraph's start
    end: int | None = None  # and where the next block starts
    raw: str = ""  # an original paragraph's text as the doc has it

    @property
    def original(self) -> bool:
        return self.start is not None


@dataclass
class Entry:
    paras: list[Para]
    end: int  # where an insertion after the last paragraph goes
    numbering: str = ""  # the separator after a step's number ("\\. ", ". "), when numbered


def read_entry(document: dict[str, Any], key: str, name: str) -> Entry | None:
    """An entry's paragraphs, each with its role, as the parser reads them."""
    from themi_home import cookbook as book
    from themi_home.quantities import weight_after_unit

    at = book.entry_range(document, key, name)
    if at is None:
        return None
    found = book.blocks(document)
    doc_end = max([int(e.get("endIndex", 0)) for e in document.get("body", {}).get("content", [])]
                  or [1])  # fmt: skip
    paras: list[Para] = []
    part, group, numbering = "", "", ""
    for n, block in enumerate(found):
        if not at[0] <= block.start < at[1]:
            continue
        nxt = found[n + 1].start if n + 1 < len(found) else doc_end - 1
        text = block.text
        plain = book._plain(text)
        role = "other"
        if block.kind != "paragraph" or block.style == book.RECIPE_STYLE or not plain:
            pass
        elif (word := book._part_word(text)) is not None and len(plain.split()) == 1:
            if (
                word == "ingredients"
                and part == "ingredients"
                and any(p.role == "line" for p in paras)
            ):
                word = "instructions"  # as the parser takes Biryani's second "Ingredients"
            part = word
        elif block.style == book.GROUP_STYLE:
            group = plain if part != "instructions" else group
        elif book.SOURCE.match(book._clean(text)) or book.SEPARATOR.match(text):
            part = "after" if part == "instructions" else part
        elif part in ("", "ingredients") and not book.NOTE.match(text):
            role = "line"
        elif part == "instructions" and not book.NOTE.match(text):
            role = "step"
            if found_number := re.match(r"^\s*\d{1,2}(\s*\\?[.)]\s+)", text):
                numbering = numbering or found_number.group(1)
        else:
            role, part = "note", "after" if part == "instructions" else part
        body = book._clean(text)
        if role == "step":
            body = clean(book.NUMBERING.sub("", body))
        elif role == "line":
            body = clean(weight_after_unit(body))
        paras.append(Para(role, body, group if role == "line" else "", block.start, nxt, text))
    return Entry(paras, at[1] if at[1] > at[0] else doc_end - 1, numbering)


def _at(paras: list[Para], role: str, text: str) -> int:
    for n, p in enumerate(paras):
        if p.role == role and p.body == text:
            return n
    raise Rejected(f"the doc has no {role} saying {text!r}")


def edit_paras(entry: Entry, ops: list[Op]) -> list[Para]:
    """The entry's paragraphs with the ops made: original ones kept, changed or gone, new
    ones in their place. Raises `Rejected` when the doc no longer has an op's old words."""
    paras = list(entry.paras)
    for o in ops:
        match o.op:
            case "replace_step" | "split_step":
                at = _at(paras, "step", o.old)
                paras[at : at + 1] = [Para("step", t) for t in o.new]
            case "merge_steps":
                at = _at(paras, "step", o.olds[0])
                steps = [n for n in range(at, len(paras)) if paras[n].role == "step"]
                taken = steps[: len(o.olds)]
                if [paras[n].body for n in taken] != list(o.olds):
                    raise Rejected("the steps to merge aren't one after another in the doc")
                for n in reversed(taken[1:]):
                    del paras[n]
                paras[at] = Para("step", o.new[0])
            case "insert_step":
                if o.after:
                    at = _at(paras, "step", o.after) + 1
                else:
                    steps = [n for n, p in enumerate(paras) if p.role == "step"]
                    at = steps[0] if steps else len(paras)
                paras.insert(at, Para("step", o.new[0]))
            case "remove_step":
                del paras[_at(paras, "step", o.old)]
            case "replace_line":
                at = _at(paras, "line", o.old)
                paras[at] = Para("line", o.new[0], paras[at].group)
            case "insert_line":
                if o.after:
                    at = _at(paras, "line", o.after) + 1
                    group = o.group or paras[at - 1].group
                    if group != paras[at - 1].group:  # the first line of its group: under
                        first = [n for n, p in enumerate(paras)  # its heading, not before it
                                 if p.role == "line" and p.group == group]  # fmt: skip
                        at = first[0] if first else at
                    paras.insert(at, Para("line", o.new[0], group))
                    continue
                else:
                    lines = [n for n, p in enumerate(paras) if p.role == "line"]
                    same = [n for n in lines if paras[n].group == o.group]
                    at = (same or lines or [0])[-1] + 1
                paras.insert(at, Para("line", o.new[0], o.group))
            case "remove_line":
                del paras[_at(paras, "line", o.old)]
            case "add_note":
                from themi_home import cookbook as book

                ends = [n for n, p in enumerate(paras) if p.original and p.role == "other"
                        and (book.SOURCE.match(p.body) or book.SEPARATOR.match(p.raw))]  # fmt: skip
                after_steps = max([n for n, p in enumerate(paras)
                                   if p.role in ("step", "note")] or [0])  # fmt: skip
                later = [n for n in ends if n > after_steps]
                paras.insert(later[0] if later else len(paras), Para("note", o.new[0]))
            case "remove_note":
                del paras[_at(paras, "note", o.old)]
    if entry.numbering:  # the steps numbered again, as the entry numbers them
        n = 0
        for k, p in enumerate(paras):
            if p.role != "step":
                continue
            n += 1
            wanted = f"{n}{entry.numbering}{p.body}"
            if not p.original or p.raw.strip() != wanted:
                paras[k] = Para("step", p.body, raw=wanted)
    return paras


def requests_for(entry: Entry, paras: list[Para]) -> list[dict[str, Any]]:
    """The batchUpdate requests, last position first so each one's indexes still hold: an
    original paragraph that changed or went is deleted; new ones are inserted before the
    next original paragraph kept (or at the entry's end), set as plain text."""
    kept = {id(p) for p in paras if p.original and p.raw}
    gone = [p for p in entry.paras if id(p) not in kept]
    inserts: list[tuple[int, list[str]]] = []
    run: list[str] = []
    for p in paras:
        if id(p) in kept:
            if run:
                assert p.start is not None
                inserts.append((p.start, run))
                run = []
        else:
            run.append(p.raw or p.body)
    if run:
        inserts.append((entry.end, run))
    moves: list[tuple[int, int, Any]] = [(p.start or 0, 0, p) for p in gone]
    moves += [(at, 1, texts) for at, texts in inserts]
    out: list[dict[str, Any]] = []
    for at, kind, what in sorted(moves, key=lambda m: (m[0], m[1]), reverse=True):
        if kind == 0:
            out.append({"deleteContentRange": {"range": {"startIndex": what.start,
                                                         "endIndex": what.end}}})  # fmt: skip
            continue
        text = "".join(f"{t}\n" for t in what)
        out.append({"insertText": {"location": {"index": at}, "text": text}})
        out.append(
            {
                "updateParagraphStyle": {
                    "range": {"startIndex": at, "endIndex": at + len(text)},
                    "paragraphStyle": {"namedStyleType": "NORMAL_TEXT"},
                    "fields": "namedStyleType",
                }
            }
        )
    return out


# ----- CF4: the `cookbook_edit` action ----------------------------------------------------

CATEGORY = "cookbook_edit"
EXECUTOR = "cookbook.edit"
STALE_TEXT = "{name} changed in {where} since the note, so nothing was written."


class CookbookEdits:
    """Stages a note's change through the trust tiers and writes it: into the recipe's doc,
    or a web recipe's own row. Then Themi's copy is read again from the doc."""

    def __init__(self, services: Any, recipes: Any, notes: Any) -> None:
        self.services = services
        self.recipes = recipes
        self.notes = notes
        self.db = services.store.db

    def install(self) -> None:
        self.services.autonomy.executors.register(EXECUTOR)(self._execute)

    async def stage(self, member: Any, note: Any, *, as_note: bool = False) -> Any:
        """The note's change (or, `as_note`, its words kept as a note), staged with their
        tap as the yes. Returns the trust tiers' outcome."""
        recipe = self.recipes.get(note.recipe_id)
        if recipe is None:
            raise Rejected("that recipe isn't kept any more")
        if as_note and note.kind != "note":
            from themi_home.cooking_notes import note_text

            words = note.said or note.words
            ops = [Op("add_note", new=(note_text(words, self.notes._today()),))]
        else:
            ops = [Op.from_json(o) for o in note.proposal.get("ops") or []]
        apply(ops, shape_of(recipe))  # still fits Themi's copy
        what = "Add a note to" if all(o.op == "add_note" for o in ops) else "Change"
        summary = f'{what} "{recipe.name}" in {self.where(recipe)}'
        payload = {"note": note.id, "recipe": recipe.id, "ops": [o.to_json() for o in ops]}
        return await self.services.autonomy.stage(
            CATEGORY, member, summary, payload, EXECUTOR, interactive=True, requested=True
        )

    def where(self, recipe: Any) -> str:
        """Where the change is made: its book's doc, or Themi's copy of a web recipe."""
        return "Themi's copy" if recipe.source == "web" else self.recipes.doc_name(recipe.book)

    async def stage_undo(self, member: Any, edit_id: int) -> Any:
        row = self.db.one("SELECT * FROM cookbook_edits WHERE id = ?", (edit_id,))
        if row is None or row["undone_at"]:
            raise Rejected("that change is undone already")
        recipe = self.recipes.get(row["recipe_id"])
        if recipe is None:
            raise Rejected("that recipe isn't kept any more")
        ops = undo_ops([Op.from_json(o) for o in json.loads(row["ops"])])
        summary = f'Undo the change to "{recipe.name}"'
        payload = {"undo": edit_id, "note": row["note_id"], "recipe": recipe.id,
                   "ops": [o.to_json() for o in ops]}  # fmt: skip
        return await self.services.autonomy.stage(
            CATEGORY, member, summary, payload, EXECUTOR, interactive=True, requested=True
        )

    async def _execute(self, payload: dict[str, Any], context: Any) -> str:
        recipe = self.recipes.get(int(payload["recipe"]))
        undo = payload.get("undo")
        note = self.notes.get(int(payload["note"])) if payload.get("note") else None
        if recipe is None:
            return "That recipe isn't kept any more, so nothing was changed."
        if undo is None and note is not None and note.edit_id is not None:
            return f"{recipe.name} has that change already."  # a retry
        if undo is not None and self.db.scalar(
            "SELECT undone_at FROM cookbook_edits WHERE id = ?", (int(undo),)
        ):
            return f"That change to {recipe.name} is undone already."
        ops = [Op.from_json(o) for o in payload["ops"]]
        where = self.where(recipe)
        before = after = ""
        if recipe.source == "web":
            try:
                shape, _ = apply(ops, shape_of(recipe))
            except Rejected:
                return self._stale(note, recipe, where, undo)
            self.db.execute(
                "UPDATE recipes SET ingredients = ?, steps = ?, notes = ?, updated_at = ? "
                "WHERE id = ?",
                (json.dumps([{"text": i.text, "group": i.group} for i in shape.ingredients]),
                 json.dumps([{"text": s.text, "group": s.group} for s in shape.steps]),
                 json.dumps(shape.notes), _now(), recipe.id),
            )  # fmt: skip
        else:
            written, before, after = await self._write_doc(recipe, ops, where)
            if not written:
                return self._stale(note, recipe, where, undo)
        edit_id = self.db.execute(
            "INSERT INTO cookbook_edits (note_id, recipe_id, book, ops, summary, revision_before,"
            " revision_after, written_at, undo_of) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (note.id if note else None, recipe.id, recipe.book,
             json.dumps([o.to_json() for o in ops]), note.summary if note else "", before, after,
             _now(), int(undo) if undo is not None else None),
        )  # fmt: skip
        if undo is not None:
            self.db.execute("UPDATE cookbook_edits SET undone_at = ? WHERE id = ?",
                            (_now(), int(undo)))  # fmt: skip
            if note is not None:
                self.notes._set(note, status="undone")
            return f"Put {recipe.name} back as it was in {where}."
        if note is not None:
            kept = all(o.op == "add_note" for o in ops)
            self.notes._set(note, status="kept" if kept else "done", edit_id=edit_id,
                            decided_by=context.member.id, decided_at=_now())  # fmt: skip
        if all(o.op == "add_note" for o in ops):
            return f"Added the note to {recipe.name} in {where}."
        return f"Changed {recipe.name} in {where}."

    async def _write_doc(self, recipe: Any, ops: list[Op], where: str) -> tuple[bool, str, str]:
        """One batchUpdate against the revision just read (read again once if someone typed
        in between), then Themi's copy read from the doc again. False when the doc no
        longer has the words."""
        from themi_google.connectors.gdocs import DocsError
        from themi_home.cookbook_save import CookbookSave

        settings = self.recipes.settings(recipe.book)
        if not settings["doc_id"] or settings["account_id"] is None:
            raise DocsError(f"There's no {where.removeprefix('the ')} doc to change.")
        client = self.recipes.client(settings["account_id"])
        doc_id = settings["doc_id"]
        key = recipe.key.removeprefix(self.recipes.book(recipe.book).prefix)
        seen: dict[str, str] = {}

        def requests(document: dict[str, Any]) -> list[dict[str, Any]] | None:
            seen["before"] = str(document.get("revisionId", ""))
            entry = read_entry(document, key, recipe.name)
            if entry is None:
                return None
            try:
                return requests_for(entry, edit_paras(entry, ops))
            except Rejected as exc:
                log.info("%s: the doc moved on (%s)", recipe.name, exc)
                return None

        written = await CookbookSave._write(client, doc_id, where, requests,
                                            nothing="nothing was changed")  # fmt: skip
        if not written:
            return False, seen.get("before", ""), ""
        after = str((await client.get(doc_id)).get("revisionId", ""))
        await self.recipes.sync(force=True, which=recipe.book)
        return True, seen.get("before", ""), after

    def _stale(self, note: Any, recipe: Any, where: str, undo: Any) -> str:
        if undo is not None:
            return f"{recipe.name} changed in {where} since, so it wasn't put back."
        if note is not None:
            self.notes.restale(note)
        return STALE_TEXT.format(name=recipe.name, where=where)


def _now() -> str:
    from themi import clock
    from themi.localtime import to_utc_iso

    return to_utc_iso(clock.now())
