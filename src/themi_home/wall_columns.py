"""F53: the wall's columns as the family chose them, on Wall frames: each person's colour,
and the order the people and Together stand in.

Nothing chosen is the wall as it always was: the people in the household's order, Together
in the middle of them, and each person coloured by their place (green, rose, blue, amber),
Together purple. A person added after a choice goes at the end in their default colour.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from themi import clock
from themi.accounts import Member
from themi.localtime import to_utc_iso
from themi.storage.db import Database

TOGETHER = "together"  # Together's key, as its column has it
TOGETHER_TONE = "family"

# The tone classes (wall.css's `.tone-*`), by the name the family picks. The first five are
# the ones the wall always had.
TONES: dict[str, str] = {
    "p0": "Green",
    "p1": "Rose",
    "p2": "Blue",
    "p3": "Amber",
    "family": "Purple",
    "p4": "Teal",
    "p5": "Plum",
    "p6": "Slate",
}
DEFAULT_TONES = ("p0", "p1", "p2", "p3")


class BadLayout(ValueError):
    """A choice that names a column or a colour the wall doesn't have."""


@dataclass(frozen=True)
class Place:
    """One column as the wall shows it: "m3" or "together", its person (None for Together),
    and its tone class."""

    key: str
    name: str
    member: Member | None
    tone: str


def key_of(member: Member) -> str:
    return f"m{member.id}"


def default_layout(members: Sequence[Member]) -> list[Place]:
    places = [
        Place(key_of(m), m.name, m, DEFAULT_TONES[i % len(DEFAULT_TONES)])
        for i, m in enumerate(members)
    ]
    middle = len(places) // 2 if len(places) > 1 else len(places)
    places.insert(middle, Place(TOGETHER, "Together", None, TOGETHER_TONE))
    return places


class WallColumns:
    def __init__(self, db: Database) -> None:
        self.db = db

    def chosen(self) -> dict[str, tuple[int, str]]:
        rows = self.db.query("SELECT key, position, tone FROM wall_columns")
        return {r["key"]: (int(r["position"]), r["tone"]) for r in rows}

    def layout(self, members: Sequence[Member]) -> list[Place]:
        """The columns in the wall's order, each with its colour."""
        chosen = self.chosen()
        defaults = default_layout(members)
        ranked = sorted(
            enumerate(defaults),
            key=lambda pair: (0, chosen[pair[1].key][0]) if pair[1].key in chosen else (1, pair[0]),
        )
        out = []
        for _, place in ranked:
            tone = chosen.get(place.key, (0, place.tone))[1]
            out.append(
                Place(place.key, place.name, place.member, tone if tone in TONES else place.tone)
            )
        return out

    def save(
        self, by: Member, members: Sequence[Member], order: Sequence[str], tones: Mapping[str, str]
    ) -> None:
        """Keep `order` (every column's key, each once) and `tones` (key -> tone class)."""
        known = {p.key: p for p in self.layout(members)}
        if sorted(order) != sorted(known):
            raise BadLayout("That isn't every column of the wall once each.")
        for key, tone in tones.items():
            if key not in known:
                raise BadLayout("That isn't a column on the wall.")
            if tone not in TONES:
                raise BadLayout("That isn't one of the wall's colours.")
        now = to_utc_iso(clock.now())
        with self.db.transaction():
            self.db.execute("DELETE FROM wall_columns")
            for position, key in enumerate(order):
                self.db.execute(
                    "INSERT INTO wall_columns (key, position, tone, updated_by, updated_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (key, position, tones.get(key, known[key].tone), by.id, now),
                )

    def reset(self) -> None:
        self.db.execute("DELETE FROM wall_columns")


def moved(order: Sequence[str], key: str, step: int) -> list[str]:
    """`order` with `key` one place up (-1) or down (+1); unchanged at either end."""
    out = list(order)
    if key not in out:
        return out
    at = out.index(key)
    to = at + step
    if 0 <= to < len(out):
        out[at], out[to] = out[to], out[at]
    return out
