"""What Themi remembers, and fixing it when it forgets.

Facts are household-wide (scope "family") or personal (scope "member", seen
only in that member's conversations). Two ways they reach the model:
- pinned facts go into the system prompt every time;
- other facts are found by full-text search on the incoming message (top 5)
  and placed in that turn as notes.
Each time a fact is put in front of the model, `last_shown_at` is stamped,
which is how context repair can tell "never saw it" from "saw it and
ignored it".

"You keep forgetting X" runs a four-way diagnosis:
  never stored          -> store it, pinned
  stored, not retrieved -> pin it, so it's always included
  stored wrong          -> correct it (and pin it)
  included but ignored  -> promote it to a standing-reminder rule
and the person is told what was found and changed. Every repair is logged.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal

from themi import clock
from themi.accounts import Member, NotFound
from themi.localtime import to_utc_iso

if TYPE_CHECKING:
    from themi.core.rules import Rulebook
    from themi.storage.db import Database

log = logging.getLogger(__name__)

Scope = Literal["family", "member"]
Diagnosis = Literal["never_stored", "not_retrieved", "stored_wrong", "ignored"]

RETRIEVE_LIMIT = 5
# A fact shown to the model this recently counts as "it was in front of you".
RECENTLY_SHOWN = timedelta(days=2)
# Word overlap below this means a correction really says something different.
SAME_MEANING = 0.6

STOPWORDS = frozenset(
    """
    a an and are as at be but by do does for from has have i if in is it its me my of on or
    our so that the their them they this to was we were what when where which who will with
    you your about again always keep keeps kept forget forgetting forgot remember please just
    """.split()
)

REPAIR_REPLIES: dict[Diagnosis, str] = {
    "never_stored": "I hadn't saved that at all. It's saved now, and it'll always be in front "
    "of me.",
    "not_retrieved": "I had it saved, but it wasn't coming up when it mattered. It's pinned "
    "now, so it's always in front of me.",
    "stored_wrong": "What I had saved was out of date. I've corrected it to: {fact}",
    "ignored": "I had that in front of me and still missed it, sorry. It's now a standing "
    "reminder, listed with the household rules.",
}


@dataclass(frozen=True)
class Fact:
    id: int
    scope: Scope
    member_id: int | None
    subject: str
    fact: str
    pinned: bool
    last_shown_at: datetime | None


@dataclass(frozen=True)
class Repair:
    diagnosis: Diagnosis
    message: str
    fact: Fact | None
    rule_id: int | None


def _fact_from_row(row: dict[str, Any]) -> Fact:
    return Fact(
        id=row["id"],
        scope=row["scope"],
        member_id=row["member_id"],
        subject=row["subject"],
        fact=row["fact"],
        pinned=bool(row["pinned"]),
        last_shown_at=datetime.fromisoformat(row["last_shown_at"])
        if row["last_shown_at"]
        else None,
    )


def terms(text: str) -> list[str]:
    """Meaningful words, for search and for comparing two statements."""
    words = re.findall(r"[a-z0-9]+", text.lower())
    return [w for w in words if w not in STOPWORDS and len(w) > 1]


def similarity(a: str, b: str) -> float:
    left, right = set(terms(a)), set(terms(b))
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


class Memory:
    def __init__(self, db: Database, rulebook: Rulebook | None = None) -> None:
        self.db = db
        self.rulebook = rulebook

    # ----- writing ------------------------------------------------------------

    def remember(
        self,
        member: Member,
        subject: str,
        fact: str,
        *,
        scope: Scope = "family",
        pinned: bool = False,
        source: str = "chat",
    ) -> Fact:
        subject, fact = subject.strip() or "general", fact.strip()
        if not fact:
            raise ValueError("a fact needs some text")
        member_id = member.id if scope == "member" else None
        existing = self.db.one(
            "SELECT * FROM facts WHERE lower(fact) = lower(?) AND scope = ? AND member_id IS ?",
            (fact, scope, member_id),
        )
        if existing is not None:
            if pinned and not existing["pinned"]:
                self.pin(existing["id"])
            return self.get(existing["id"])
        now = to_utc_iso(clock.now())
        fact_id = self.db.execute(
            "INSERT INTO facts (scope, member_id, subject, fact, pinned, source, created_by, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (scope, member_id, subject, fact, int(pinned), source, member.id, now, now),
        )
        return self.get(fact_id)

    def pin(self, fact_id: int, pinned: bool = True) -> Fact:
        self.db.execute(
            "UPDATE facts SET pinned = ?, updated_at = ? WHERE id = ?",
            (int(pinned), to_utc_iso(clock.now()), fact_id),
        )
        return self.get(fact_id)

    def correct(self, fact_id: int, fact: str) -> Fact:
        self.db.execute(
            "UPDATE facts SET fact = ?, updated_at = ? WHERE id = ?",
            (fact.strip(), to_utc_iso(clock.now()), fact_id),
        )
        return self.get(fact_id)

    def forget(self, fact_id: int) -> None:
        self.db.execute("DELETE FROM facts WHERE id = ?", (fact_id,))

    # ----- reading ------------------------------------------------------------

    def get(self, fact_id: int) -> Fact:
        row = self.db.one("SELECT * FROM facts WHERE id = ?", (fact_id,))
        if row is None:
            raise NotFound(f"no fact with id {fact_id}")
        return _fact_from_row(row)

    def visible(self, member: Member) -> list[Fact]:
        rows = self.db.query(
            "SELECT * FROM facts WHERE scope = 'family' OR member_id = ? ORDER BY id", (member.id,)
        )
        return [_fact_from_row(r) for r in rows]

    def pinned(self, member: Member) -> list[Fact]:
        return [f for f in self.visible(member) if f.pinned]

    def search(
        self,
        query: str,
        member: Member,
        *,
        limit: int = RETRIEVE_LIMIT,
        include_pinned: bool = False,
    ) -> list[Fact]:
        """Facts this member may see that match words in `query`, best first."""
        words = terms(query)[:16]
        if not words:
            return []
        match = " OR ".join(f'"{w}"' for w in words)
        rows = self.db.query(
            "SELECT f.* FROM facts_fts JOIN facts f ON f.id = facts_fts.rowid "
            "WHERE facts_fts MATCH ? AND (f.scope = 'family' OR f.member_id = ?) "
            "AND (? OR f.pinned = 0) ORDER BY bm25(facts_fts) LIMIT ?",
            (match, member.id, int(include_pinned), limit),
        )
        return [_fact_from_row(r) for r in rows]

    def for_prompt(self, member: Member, message: str) -> tuple[list[Fact], list[Fact]]:
        """(pinned facts for the system prompt, retrieved notes for this turn), stamped as shown."""
        pinned = self.pinned(member)
        retrieved = self.search(message, member)
        shown = [f.id for f in (*pinned, *retrieved)]
        if shown:
            placeholders = ", ".join("?" for _ in shown)
            self.db.execute(
                f"UPDATE facts SET last_shown_at = ? WHERE id IN ({placeholders})",
                (to_utc_iso(clock.now()), *shown),
            )
        return pinned, retrieved

    # ----- context repair -----------------------------------------------------

    def repair(self, member: Member, forgotten: str, correct: str = "") -> Repair:
        """Work out why `forgotten` was missed, fix the cause, and log it."""
        statement = (correct or forgotten).strip()
        candidates = self.search(f"{forgotten} {correct}", member, limit=3, include_pinned=True)
        match = candidates[0] if candidates else None
        rule_id: int | None = None

        if match is None:
            fact = self.remember(
                member, _subject_of(forgotten), statement, pinned=True, source="repair"
            )
            diagnosis: Diagnosis = "never_stored"
            fix = f"saved and pinned fact {fact.id}"
        elif correct and similarity(match.fact, correct) < SAME_MEANING:
            fact = self.pin(self.correct(match.id, correct).id)
            diagnosis = "stored_wrong"
            fix = f"corrected and pinned fact {fact.id} (was: {match.fact})"
        elif not self._recently_shown(match):
            fact = self.pin(match.id)
            diagnosis = "not_retrieved"
            fix = f"pinned fact {fact.id}"
        else:
            fact = match
            if self.rulebook is None:
                raise RuntimeError("promoting to a standing reminder needs the rulebook")
            rule = self.rulebook.add_standing_reminder(
                member, f"Keep in mind: {match.subject}", f"Always keep in mind: {match.fact}"
            )
            rule_id = rule.id
            diagnosis = "ignored"
            fix = f"promoted fact {fact.id} to standing reminder rule {rule.id}"

        self.db.execute(
            "INSERT INTO context_repairs (member_id, complaint, diagnosis, fix, fact_id, rule_id, "
            "created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (member.id, forgotten[:300], diagnosis, fix, fact.id, rule_id, to_utc_iso(clock.now())),
        )
        log.info("Context repair for member %s: %s (%s)", member.id, diagnosis, fix)
        message = REPAIR_REPLIES[diagnosis].format(fact=fact.fact)
        return Repair(diagnosis, message, fact, rule_id)

    def _recently_shown(self, fact: Fact) -> bool:
        if fact.pinned:
            return True
        return fact.last_shown_at is not None and clock.now() - fact.last_shown_at < RECENTLY_SHOWN

    def repairs(self, member_id: int | None = None) -> list[dict[str, Any]]:
        if member_id is None:
            return self.db.query("SELECT * FROM context_repairs ORDER BY id")
        return self.db.query(
            "SELECT * FROM context_repairs WHERE member_id = ? ORDER BY id", (member_id,)
        )


def _subject_of(text: str) -> str:
    words = terms(text)
    return " ".join(words[:3]) or "general"
