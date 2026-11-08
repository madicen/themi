"""Places they name instead of an address (F29e, bug #154).

"When should we leave for tutoring at my parent's house?" sent "parent's house" to the
map, which found a place called that near Oroville: 3 hr 20 min, "leave at 12:10 pm". The
family had told Themi the address ("Erin's parents' address is 790 La Para Ave, Palo Alto,
CA 94306"). A named place ("my parents'", "the in-laws'", "grandma's", "home", "work") is
looked up in what Themi remembers first; one it can't find isn't guessed on the map.

Erin's parents are Michael's in-laws: "in-laws" from one partner means the other's
parents.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from themi.accounts import Member
from themi.storage import Database

# A word that makes a phrase a place someone is, not an address.
KIN = {
    "parent": "parent",
    "parents": "parent",
    "mom": "mom",
    "mum": "mom",
    "mother": "mom",
    "dad": "dad",
    "father": "dad",
    "grandma": "grandma",
    "grandmother": "grandma",
    "grandpa": "grandpa",
    "grandfather": "grandpa",
    "nana": "grandma",
    "sister": "sister",
    "brother": "brother",
    "aunt": "aunt",
    "uncle": "uncle",
    "work": "work",
    "office": "work",
    "school": "school",
}
IN_LAWS = re.compile(r"\bin[\s-]?laws?\b")
HOME = re.compile(r"^(?:(?:my|our|the)\s+)?(?:home|house|place)$")
WORD = re.compile(r"[a-z]+")
# The address in a remembered fact: from a street number to the end of the sentence.
ADDRESS = re.compile(r"\b\d+[A-Za-z]?\s+[A-Za-z][^;\n]*?(?=\.\s|\.$|;|\n|$)")
NOT_SURE_TEXT = (
    "Not sure where '{phrase}' is: no address for it is remembered. Ask them for the "
    "address once, and remember_fact it ('<whose> address is <address>')."
)


@dataclass(frozen=True)
class Named:
    """A place they named: its address if Themi knows it."""

    phrase: str
    address: str | None


def _kin(phrase: str) -> str | None:
    text = phrase.lower().replace("\N{RIGHT SINGLE QUOTATION MARK}", "'")
    if IN_LAWS.search(text):
        return "in-laws"
    for word in WORD.findall(text.replace("'s", " ").replace("s'", "s ")):
        if word in KIN:
            return KIN[word]
    return None


def named_place(
    db: Database, member: Member, family: list[Member], phrase: str, home: str | None
) -> Named | None:
    """None when `phrase` is an address (or anything else for the map); otherwise the place
    it names, with the address Themi knows for it, or none."""
    phrase = " ".join(phrase.split())
    if not phrase or any(c.isdigit() for c in phrase):
        return None
    if HOME.match(phrase.lower()):
        return Named(phrase, home)
    kin = _kin(phrase)
    if kin is None:
        return None
    others = [m for m in family if m.id != member.id]
    if kin == "in-laws":  # with one partner, their parents
        whose, kin = (others[0] if len(others) == 1 else None), "parent"
    else:
        whose = member
    rows = db.query(
        "SELECT fact FROM facts WHERE scope = 'family' OR member_id = ? ORDER BY id DESC",
        (member.id,),
    )
    names = [m.name for m in family]
    best: str | None = None
    for row in rows:
        fact = str(row["fact"])
        address = ADDRESS.search(fact)
        if address is None or _kin(fact) != kin:
            continue
        found = address.group(0).strip().rstrip(".")
        named = {n for n in names if re.search(rf"\b{re.escape(n)}\b", fact, re.I)}
        if whose is not None and named == {whose.name}:
            return Named(phrase, found)
        if not named:  # "Grandma's address is ...": whose, unsaid
            best = best or found
    return Named(phrase, best)
