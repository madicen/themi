"""Look-ahead on the cook screen (CK4): what a later step needs started early.

RC3a's finders (`cooking.ahead_of_time`) say what needs time before cooking starts. These run
over the steps still to come, each item tied to the step it's for: an oven to preheat, water
to boil, a soak, a marinade, a rest. The strip shows the nearest one as an offer: "Step 5
wants the oven at 400°F. Start it now?" [Done] [Later]. [Later] hides it until the step
before that one. Both answers are kept (`ahead_done`). What the ready phase listed and they
said [Done] to isn't offered again; nothing to say, no strip.

"While that simmers": with a timer of 10 minutes or more running, the strip may name what
the next step uses, from CK2's links and RC3a's prep words only ("Step 4 uses the
scallions, sliced."). Never a model's advice. Every line is an offer or a plain fact, never
"you should" or "don't forget".
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from themi_home.cooking import PREHEAT, PREP_WORDS, and_words, step_parts

if TYPE_CHECKING:
    from themi_home.cooking import Cooking, Session
    from themi_home.recipes import Recipe

SIMMER_MINUTES = 10  # a timer this long or longer: time to look at the next step
TIME = (
    r"(?:[^.]*?\b(?:for\s+)?(?:about\s+|at least\s+)?"
    r"(?P<n>\d+)\s*(?P<unit>minutes?|mins?|hours?|hrs?))?"
)
BOIL = re.compile(
    r"\b(?:bring|brought)\b[^.]{0,60}\bto (?:a |the )?boil\b|\bboiling (?:salted )?water\b"
    r"|\bboil (?:a pot of |some |the )?(?:salted )?water\b",
    re.IGNORECASE,
)
SOAK = re.compile(rf"\bsoak(?:ing)?\b{TIME}", re.IGNORECASE)  # not "soaked": done before
MARINATE = re.compile(rf"\bmarinat(?:e|ing)\b{TIME}", re.IGNORECASE)
REST = re.compile(rf"\b(?:let (?:it |them |the \w+ )?rest|rest for|to rest){TIME}", re.IGNORECASE)
MUST = ("preheat", "soak", "marinate")  # CK7: on a lighter day, only these


@dataclass(frozen=True)
class LookAhead:
    key: str  # "preheat:4": what, and the step (part index) it's for
    kind: str
    part: int
    text: str

    @property
    def must(self) -> bool:
        return self.kind in MUST


def _for(match: re.Match[str]) -> str:
    n, unit = match.group("n"), match.group("unit")
    if not n:
        return ""
    return f" ({n} min)" if unit.lower().startswith("m") else f" ({n} hr)"


def look_ahead(recipe: Recipe) -> list[LookAhead]:
    """Every early start the steps ask for, in order."""
    found: list[LookAhead] = []
    for i, part in enumerate(step_parts(recipe)):
        step, text = part.label, part.text

        def add(kind: str, words: str, *, i: int = i) -> None:
            found.append(LookAhead(f"{kind}:{i}", kind, i, words))

        if heat := PREHEAT.search(text):
            unit = (heat.group("scale") or "F").upper()
            add("preheat", f"Step {step} wants the oven at {heat.group('temp')}°{unit}. "
                           "Start it now?")  # fmt: skip
        if BOIL.search(text):
            add("boil", f"Step {step} wants a pot of boiling water. Put it on now?")
        if soak := SOAK.search(text):
            add("soak", f"Step {step} has a soak{_for(soak)}. Start it now?")
        if marinade := MARINATE.search(text):
            add("marinate", f"Step {step} marinates{_for(marinade)}. Start it now?")
        if rest := REST.search(text):
            add("rest", f"Step {step} has a rest{_for(rest)}. Start that part now?")
    return found


def _ready_done(session: Session, item: LookAhead) -> bool:
    """The ready phase listed it and they said [Done] (or ticked it) there."""
    words = {"preheat": "preheat", "soak": "soak"}.get(item.kind)
    return bool(words) and any(a.get("done") and a["text"].startswith(words) for a in session.ahead)


def current(session: Session) -> int:
    """The part they're on; before the steps, before the first."""
    return session.step if session.phase == "cook" else -1


def offers(session: Session, recipe: Recipe, *, must_only: bool = False) -> list[LookAhead]:
    """The look-ahead offers to show now, nearest first."""
    if session.phase not in ("gather", "prep", "cook"):
        return []
    now = current(session)
    out = []
    for item in look_ahead(recipe):
        answer = session.ahead_done.get(item.key) or {}
        if item.part <= now or answer.get("status") == "done" or _ready_done(session, item):
            continue
        if must_only and not item.must:
            continue
        if answer.get("status") == "later" and not (now == item.part - 1 > answer.get("at", -1)):
            continue  # [Later]: back at the step before that one
        out.append(item)
    return sorted(out, key=lambda item: item.part)


def answer(session: Session, key: str, status: str) -> bool:
    """[Done] or [Later] on an offer, kept with the step it was said at."""
    if status not in ("done", "later") or not re.fullmatch(r"[a-z]+:\d+", key):
        return False
    session.ahead_done[key] = {"status": status, "at": current(session)}
    return True


def simmer_line(cooking: Cooking, session: Session, recipe: Recipe) -> str:
    """With a long timer running: what the next step uses, from the links and the lines'
    own prep words."""
    if session.phase != "cook":
        return ""
    long = cooking.db.scalar(
        "SELECT COUNT(*) FROM cooking_timers WHERE member_id = ? AND fired_at IS NULL "
        "AND cancelled_at IS NULL AND minutes >= ?",
        (session.member_id, SIMMER_MINUTES),
    )
    parts = step_parts(recipe)
    if not long or session.step + 1 >= len(parts):
        return ""
    from themi_home.cooking_screen import step_index

    nxt = parts[session.step + 1]
    items = cooking.groceries.known(recipe)
    linked = cooking.links.links(recipe, items).get(step_index(nxt.label), [])
    if step_index(nxt.label) == step_index(parts[session.step].label):
        return ""  # the same step, split in two: nothing new
    names = []
    for n in linked:
        item = items[n]
        prep = f", {item.note}" if item.note and PREP_WORDS.search(item.note) else ""
        names.append(f"the {item.item}{prep}")
    if not names:
        return ""
    return f"Step {nxt.label} uses {and_words(names)}."


def strip(
    cooking: Cooking, session: Session, recipe: Recipe, *, must_only: bool = False
) -> dict[str, Any] | None:
    """What the strip shows: the nearest offer, else the simmer line, else nothing."""
    found = offers(session, recipe, must_only=must_only)
    if found:
        return {"kind": "offer", "key": found[0].key, "text": found[0].text}
    if must_only:
        return None
    line = simmer_line(cooking, session, recipe)
    return {"kind": "simmer", "text": line} if line else None
