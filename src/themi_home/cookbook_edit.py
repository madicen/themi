"""Changes to a recipe from a cooking note (CF3 checks them, CF4 writes them).

A change is a short list of ops, each anchored on the recipe's own words, never on a number
alone: `replace_step` (old, new), `split_step` (old, two or more new), `merge_steps` (olds,
new), `insert_step` (after, new), `remove_step` (old), `replace_line`, `insert_line` (after,
new, group), `remove_line`, `add_note` (new) and `remove_note` (old). An op whose old words
aren't the recipe's is refused (`Rejected`), so a proposal can't say what the recipe never
said. `apply` gives the recipe as it would be; `inverse` gives the ops that put it back.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from themi_home.cookbook import Line

STEP_OPS = ("replace_step", "split_step", "merge_steps", "insert_step", "remove_step")
LINE_OPS = ("replace_line", "insert_line", "remove_line")
NOTE_OPS = ("add_note", "remove_note")
OPS = (*STEP_OPS, *LINE_OPS, *NOTE_OPS)
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
                steps[at : at + len(o.olds)] = [Line(o.new[0], steps[at].group)]
                done.append(o)
            case "insert_step":
                at = 0 if not o.after else _find(steps, o.after, "step") + 1
                group = o.group or (steps[at - 1].group if at > 0 else "")
                steps.insert(at, Line(o.new[0], group))
                done.append(Op(o.op, new=o.new, after=_after(steps, at), group=group))
            case "remove_step":
                at = _find(steps, o.old, "step")
                gone = steps.pop(at)
                done.append(Op(o.op, o.old, after=_after(steps, at), group=gone.group))
            case "replace_line":
                at = _find(ing, o.old, "ingredient line")
                ing[at] = Line(o.new[0], ing[at].group)
                done.append(o)
            case "insert_line":
                if o.after:
                    at = _find(ing, o.after, "ingredient line") + 1
                    group = ing[at - 1].group
                else:  # at the end of its group, or of the list
                    group = o.group
                    tail = [n for n, line in enumerate(ing) if line.group == group]
                    at = tail[-1] + 1 if tail else len(ing)
                ing.insert(at, Line(o.new[0], group))
                done.append(Op(o.op, new=o.new, after=_after(ing, at), group=group))
            case "remove_line":
                at = _find(ing, o.old, "ingredient line")
                gone = ing.pop(at)
                done.append(Op(o.op, o.old, after=_after(ing, at), group=gone.group))
            case "add_note":
                notes.append(o.new[0])
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
