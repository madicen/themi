"""Places they name instead of an address (F29e, bug #154; F46b, bug #217).

"When should we leave for tutoring at my parent's house?" sent "parent's house" to the
map, which found a place called that near Oroville: 3 hr 20 min, "leave at 12:10 pm". The
family had told Themi the address ("Erin's parents' address is 790 La Para Ave, Palo Alto,
CA 94306"). A named place ("my parents'", "the in-laws'", "grandma's", "home", "work") is
looked up in what Themi remembers first; one it can't find isn't guessed on the map.

Erin's parents are Michael's in-laws: "in-laws" from one partner means the other's
parents.

F57b: a place can also be saved as one (`places`, the `remember_place` tool, the Rules &
memory page): "when I say Stanford, take me to the visitor parking lot at 200 S Pasteur
Dr". A saved place's name or other names are looked up before everything else, and it can
carry a note (visiting hours) and how many minutes early they like to arrive there.

F58e (bug #251): its hours by weekday, as data ("weekdays 6:30-8:30 pm, weekends 12-8:30
pm"), so the day an event's on gets that day's hours: the note's free text let a Monday
visit take the weekend's 12-8:30. The turn's place line gives the day named in the message,
and `add_calendar_event` refuses a time outside that day's hours.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, time, timedelta
from typing import Any, Literal

from themi import clock
from themi.accounts import Member, NotFound
from themi.localtime import to_utc_iso
from themi.standard.business_hours import (
    DAY_NAMES,
    Hours,
    hours_from_json,
    hours_json,
    parse_hours,
)
from themi.standard.tasks import clock_words
from themi.storage import Database

Scope = Literal["family", "member"]

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
    """A place they named: its address if Themi knows it. `saved`: the saved place it is
    (F57b), with its note and minutes early."""

    phrase: str
    address: str | None
    saved: SavedPlace | None = None


@dataclass(frozen=True)
class SavedPlace:
    """F57b: a place saved by name."""

    id: int
    scope: Scope
    member_id: int | None
    name: str
    aliases: str
    address: str
    note: str
    arrive_early: int
    hours: Hours = field(default_factory=dict)  # F58e: weekday (Monday 0) -> span; {} unsaid

    def names(self) -> list[str]:
        """Its name and other names, in `_words` form."""
        found = [_words(self.name), *(_words(a) for a in self.aliases.split(","))]
        return [n for n in dict.fromkeys(found) if n]

    def line(self, day: date | None = None) -> str:
        """How it's put in front of the model; with `day` (the day the message names,
        F58e), that day's hours too."""
        other = f" (also called {self.aliases})" if self.aliases else ""
        text = f"Place: {self.name}{other} means {self.address}."
        if self.hours:
            text += f" Hours: {hours_words(self.hours)}."
            if day is not None:
                text += f" On {day_label(day)}: {self.hours_on(day)}."
        if self.note:
            text += f" {self.note.rstrip('.')}."
        if self.arrive_early:
            text += f" They like to get there {self.arrive_early} minutes early."
        return text

    @property
    def hours_text(self) -> str:
        """Its hours in words, for the page ("" when none are saved)."""
        return hours_words(self.hours) if self.hours else ""

    def hours_on(self, day: date) -> str:
        """ "6:30-8:30 pm", or "closed" (F58e)."""
        span = self.hours.get(day.weekday())
        return span_words(span) if span else "closed"


def _saved_from_row(row: dict[str, Any]) -> SavedPlace:
    return SavedPlace(
        id=row["id"],
        scope=row["scope"],
        member_id=row["member_id"],
        name=row["name"],
        aliases=row["aliases"],
        address=row["address"],
        note=row["note"],
        arrive_early=int(row["arrive_early"]),
        hours=hours_from_json(row["hours"]) if row.get("hours") else {},
    )


def span_words(span: tuple[time, time]) -> str:
    """ "6:30-8:30 pm", "12-8:30 pm", "9 am-1 pm"."""
    opens, closes = clock_words(span[0]), clock_words(span[1])
    half = closes[-2:]
    if opens.endswith(half) and opens[-2:] in ("am", "pm"):
        opens = opens[:-3]
    return f"{opens}-{closes}"


def hours_words(hours: Hours) -> str:
    """ "Mon-Fri 6:30-8:30 pm; Sat-Sun 12-8:30 pm" (closed days said as closed)."""
    groups: list[tuple[list[int], tuple[time, time] | None]] = []
    for day in range(7):
        span = hours.get(day)
        if groups and groups[-1][1] == span:
            groups[-1][0].append(day)
        else:
            groups.append(([day], span))
    parts = []
    for days, span in groups:
        named = DAY_NAMES[days[0]][:3] + (f"-{DAY_NAMES[days[-1]][:3]}" if len(days) > 1 else "")
        parts.append(f"{named} {span_words(span)}" if span else f"{named} closed")
    return "; ".join(parts)


def day_label(day: date) -> str:
    """ "Mon 23 Nov"."""
    return f"{day:%a} {day.day} {day:%b}"


def read_hours(text: str) -> Hours:
    """Hours as said ("weekdays 6:30-8:30 pm, weekends 12-8:30 pm"); ValueError when none
    can be read."""
    hours = parse_hours(text)
    if not hours:
        raise ValueError(
            "couldn't read those hours; say them per day or as weekdays and weekends, "
            "e.g. 'weekdays 6:30-8:30 pm, weekends 12-8:30 pm'"
        )
    return hours


_WEEKDAYS = {name.lower(): i for i, name in enumerate(DAY_NAMES)}
_DAY_WORD = re.compile(
    r"\b(today|tonight|tomorrow|tmrw|monday|tuesday|wednesday|thursday|friday|saturday|"
    r"sunday)\b"
)


def day_named(text: str, today: date) -> date | None:
    """The day a message names: today, tomorrow, or the next such weekday (today's own
    name is today). None when it names none."""
    found = _DAY_WORD.search(text.lower())
    if found is None:
        return None
    word = found.group(1)
    if word in ("today", "tonight"):
        return today
    if word in ("tomorrow", "tmrw"):
        return today + timedelta(days=1)
    return today + timedelta(days=(_WEEKDAYS[word] - today.weekday()) % 7)


def _aliases(text: str, name: str) -> str:
    kept: list[str] = []
    for part in text.split(","):
        alias = " ".join(part.split())
        if alias and _words(alias) != _words(name) and _words(alias) not in map(_words, kept):
            kept.append(alias)
    return ", ".join(kept[:8])


def _place_values(
    name: str, address: str, aliases: str, note: str, arrive_early: int
) -> tuple[str, tuple[str, str, str, int]]:
    name, address = " ".join(name.split())[:100], " ".join(address.split())[:200]
    if not _words(name) or not address:
        raise ValueError("a place needs a name and an address")
    early = max(0, min(120, int(arrive_early)))
    return name, (_aliases(aliases, name), address, " ".join(note.split())[:300], early)


class Places:
    """F57b: the places they've saved by name."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def save(
        self,
        member: Member,
        name: str,
        address: str,
        *,
        aliases: str = "",
        note: str = "",
        arrive_early: int = 0,
        scope: Scope = "family",
        hours: Hours | None = None,
    ) -> SavedPlace:
        """Save a place, or update the one with this name (any case) that they can see.
        `hours`: None keeps what an existing place has (F58e)."""
        existing = self._named(member, name, scope)
        if existing is not None:
            return self.update(
                existing.id,
                name,
                address,
                aliases=aliases,
                note=note,
                arrive_early=arrive_early,
                hours=existing.hours if hours is None else hours,
            )
        name, values = _place_values(name, address, aliases, note, arrive_early)
        now = to_utc_iso(clock.now())
        member_id = member.id if scope == "member" else None
        place_id = self.db.execute(
            "INSERT INTO places (scope, member_id, name, aliases, address, note, arrive_early, "
            "hours, created_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (scope, member_id, name, *values, _hours_text(hours), member.id, now, now),
        )
        return self.get(place_id)

    def update(
        self,
        place_id: int,
        name: str,
        address: str,
        *,
        aliases: str = "",
        note: str = "",
        arrive_early: int = 0,
        hours: Hours | None = None,
    ) -> SavedPlace:
        """`hours`: None keeps the place's own."""
        name, values = _place_values(name, address, aliases, note, arrive_early)
        kept = self.get(place_id).hours if hours is None else hours
        self.db.execute(
            "UPDATE places SET name = ?, aliases = ?, address = ?, note = ?, arrive_early = ?, "
            "hours = ?, updated_at = ? WHERE id = ?",
            (name, *values, _hours_text(kept), to_utc_iso(clock.now()), place_id),
        )
        return self.get(place_id)

    def _named(self, member: Member, name: str, scope: Scope) -> SavedPlace | None:
        said = _words(name)
        for place in self.visible(member):
            if place.scope == scope and _words(place.name) == said:
                return place
        return None

    def get(self, place_id: int) -> SavedPlace:
        row = self.db.one("SELECT * FROM places WHERE id = ?", (place_id,))
        if row is None:
            raise NotFound(f"no place with id {place_id}")
        return _saved_from_row(row)

    def remove(self, place_id: int) -> None:
        self.db.execute("DELETE FROM places WHERE id = ?", (place_id,))

    @staticmethod
    def can_edit(member: Member, place: SavedPlace) -> bool:
        """As facts: anyone may edit a household place; a personal one only its owner."""
        return place.scope == "family" or place.member_id == member.id

    def visible(self, member: Member) -> list[SavedPlace]:
        """Household places and their own, their own first, newest first."""
        rows = self.db.query(
            "SELECT * FROM places WHERE scope = 'family' OR member_id = ? "
            "ORDER BY scope = 'family', id DESC",
            (member.id,),
        )
        return [_saved_from_row(r) for r in rows]

    def find(self, member: Member, phrase: str) -> SavedPlace | None:
        """The place `phrase` names: its name or another name, or a phrase holding one as
        whole words ("the Stanford lot"), the longest name winning; or its address (an
        event whose location is the place's address, as the model puts it)."""
        said = _words(phrase)
        if not said:
            return None
        if any(c.isdigit() for c in phrase):
            spoken = " ".join(re.findall(r"[a-z0-9]+", phrase.lower()))
            for place in self.visible(member):
                street = _address_words(place.address)
                if street and re.search(rf"(?:^| ){re.escape(street)}(?: |$)", spoken):
                    return place
            return None
        best: tuple[int, SavedPlace] | None = None
        for place in self.visible(member):
            for name in place.names():
                if name == said:
                    return place
                if re.search(rf"\b{re.escape(name)}\b", said) and (
                    best is None or len(name) > best[0]
                ):
                    best = (len(name), place)
        return best[1] if best else None

    def mentioned(self, member: Member, text: str) -> list[SavedPlace]:
        """The places `text` names, as whole words."""
        said = _words(text)
        return [
            place
            for place in self.visible(member)
            if any(re.search(rf"\b{re.escape(n)}\b", said) for n in place.names())
        ]

    def search(self, member: Member, query: str) -> list[SavedPlace]:
        """Places whose name, other names, address or note share a word with `query`."""
        wanted = {w for w in _words(query).split() if len(w) > 2}
        found = []
        for place in self.visible(member):
            words = set(
                _words(f"{place.name} {place.aliases} {place.address} {place.note}").split()
            )
            if wanted & words:
                found.append(place)
        return found


def _hours_text(hours: Hours | None) -> str:
    return hours_json(hours) if hours else ""


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
    if not phrase:
        return None
    saved = Places(db).find(member, phrase)  # F57b: a saved place (by name or address) first
    if saved is not None:
        return Named(phrase, saved.address, saved)
    if any(c.isdigit() for c in phrase):
        return None
    if HOME.match(phrase.lower()):
        return Named(phrase, home)
    kin = _kin(phrase)
    if kin is None:
        return _remembered(db, member, phrase)
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


def _words(text: str) -> str:
    """Lower-case words only: "Stanford's visitor parking" → "stanford visitor parking"."""
    text = text.lower().replace("\N{RIGHT SINGLE QUOTATION MARK}", "'").replace("'s", "")
    return " ".join(WORD.findall(text))


def _address_words(text: str) -> str:
    """An address's number and street ("200 s pasteur dr"), lower-case, for comparing."""
    first = text.split(",")[0].lower()
    return " ".join(re.findall(r"[a-z0-9]+", first))


def _remembered(db: Database, member: Member, phrase: str) -> Named | None:
    """F46b (bug #217): a place named with no kin word ("Stanford visitor parking") whose
    address they told Themi ("Stanford visitor parking address is 200 S Pasteur Dr, ..."),
    newest first: the phrase comes before the address in the fact. None when no fact names
    it, so the phrase goes to the map as before."""
    said = _words(phrase)
    if not said:
        return None
    rows = db.query(
        "SELECT fact FROM facts WHERE scope = 'family' OR member_id = ? ORDER BY id DESC",
        (member.id,),
    )
    for row in rows:
        fact = str(row["fact"])
        address = ADDRESS.search(fact)
        if address is None:
            continue
        if re.search(rf"\b{re.escape(said)}\b", _words(fact[: address.start()])):
            return Named(phrase, address.group(0).strip().rstrip("."))
    return None
