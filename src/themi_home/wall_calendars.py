"""F55f (Michael's idea #239: "turn off my work calendar so it's not as spammy"): the week
ahead's calendars, each a chip a tap turns off there (and on again), and the same as a
checklist on the Wall frames page.

A calendar is named as the family knows it: one more than one person reads keeps its own
name ("Madicen Family"); someone's primary one, or one named by their own address, is them
("Erin"); one named by another address is theirs by its domain ("Michael's Stackadapt");
another is theirs by its name ("Erin's Work"), unless its name already says whose
("Michael (Personal)").
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from themi import clock
from themi.accounts import Member
from themi.localtime import to_utc_iso
from themi.storage.db import Database


@dataclass(frozen=True)
class KnownCalendar:
    calendar_id: str
    name: str  # as the wall says it
    member_id: int | None  # whose; None for one more than one person reads


class WallCalendars:
    def __init__(self, db: Database) -> None:
        self.db = db

    def hidden(self) -> set[str]:
        return {
            r["calendar_id"] for r in self.db.query("SELECT calendar_id FROM wall_hidden_calendars")
        }

    def toggle(self, calendar_id: str, by: Member | None = None) -> bool:
        """Off if it was on, on if it was off. Returns whether it's off now."""
        if calendar_id in self.hidden():
            self.db.execute(
                "DELETE FROM wall_hidden_calendars WHERE calendar_id = ?", (calendar_id,)
            )
            return False
        self.db.execute(
            "INSERT INTO wall_hidden_calendars (calendar_id, hidden_by, hidden_at) "
            "VALUES (?, ?, ?)",
            (calendar_id, by.id if by else None, to_utc_iso(clock.now())),
        )
        return True

    def save(self, hidden: Iterable[str], by: Member | None = None) -> None:
        now = to_utc_iso(clock.now())
        with self.db.transaction():
            self.db.execute("DELETE FROM wall_hidden_calendars")
            for calendar_id in sorted(set(hidden)):
                self.db.execute(
                    "INSERT INTO wall_hidden_calendars (calendar_id, hidden_by, hidden_at) "
                    "VALUES (?, ?, ?)",
                    (calendar_id, by.id if by else None, now),
                )

    def known(self, members: Sequence[Member]) -> dict[str, KnownCalendar]:
        """Every calendar Themi reads for the household, by id, named for the wall."""
        rows = self.db.query(
            "SELECT c.calendar_id, c.name, a.address, a.member_id FROM member_calendars c "
            "JOIN linked_accounts a ON a.id = c.account_id ORDER BY a.member_id, c.name"
        )
        names = {m.id: m.name for m in members}
        readers: dict[str, set[int]] = {}
        for row in rows:
            readers.setdefault(row["calendar_id"], set()).add(int(row["member_id"]))
        out: dict[str, KnownCalendar] = {}
        for row in rows:
            calendar_id = str(row["calendar_id"])
            if calendar_id in out or int(row["member_id"]) not in names:
                continue
            if len(readers[calendar_id]) > 1:
                out[calendar_id] = KnownCalendar(calendar_id, str(row["name"]), None)
                continue
            member_id = int(row["member_id"])
            out[calendar_id] = KnownCalendar(
                calendar_id,
                label(names[member_id], str(row["name"]), str(row["address"] or "")),
                member_id,
            )
        return out


def label(person: str, name: str, address: str) -> str:
    """How the wall names one person's calendar (see the module's doc)."""
    name = " ".join(name.split())
    if not name or name.lower() in ("primary", address.lower()):
        return person
    if "@" in name:
        domain = name.rsplit("@", 1)[1].split(".")[0]
        return f"{person}'s {domain[:1].upper()}{domain[1:]}" if domain else person
    if person.lower() in name.lower():
        return name
    return f"{person}'s {name}"
