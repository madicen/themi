"""What Themi remembers, and fixing it when it forgets.

Facts are household-wide (scope "family") or personal (scope "member", seen
only in that member's conversations). Two ways they reach the model:
- pinned facts go into the system prompt every time;
- other facts are found by full-text search on the incoming message (top 5)
  and placed in that turn as notes. F57a: a fact's search words ("Dad, hospital, visit")
  are searched with it, and the person's last two messages fill any places the latest one
  leaves, so a follow-up ("what time should we leave?") still finds what it's about. The
  model can also look facts up itself with `search_memory`.
- F57b: saved places named in the message (or the earlier two) come with the notes, and
  a pinned fact that hasn't matched anything said or looked up in 8 weeks is unpinned by
  the daily `memory.unpin_idle` job: still saved, still found when it's relevant.
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
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal
from zoneinfo import ZoneInfo

from themi import clock
from themi.accounts import Member, NotFound
from themi.core import keys
from themi.core.tools import ToolContext, ToolFailed, tool
from themi.localtime import member_day, to_utc_iso
from themi.modules import Module, ModuleContext
from themi.modules.groups import BEHIND_THE_SCENES
from themi.modules.prompt import PromptFragment
from themi.standard.places import Places, day_named, read_hours

if TYPE_CHECKING:
    from themi.core.rules import Rulebook
    from themi.storage.db import Database

log = logging.getLogger(__name__)

Scope = Literal["family", "member"]
Diagnosis = Literal["never_stored", "not_retrieved", "stored_wrong", "ignored"]

RETRIEVE_LIMIT = 5
# F57a: what search_memory returns at most, and how many search words a fact keeps.
LOOKUP_LIMIT = 8
KEYWORDS_LIMIT = 12
# F57b: a pinned fact that hasn't come up for this long is unpinned.
UNPIN_AFTER = timedelta(weeks=8)
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
    keywords: str = ""
    last_matched_at: datetime | None = None
    pinned_at: datetime | None = None
    unpinned_at: datetime | None = None


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
        keywords=row.get("keywords") or "",
        last_matched_at=_when(row.get("last_matched_at")),
        pinned_at=_when(row.get("pinned_at")),
        unpinned_at=_when(row.get("unpinned_at")),
    )


def _when(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def keyword_text(words: str | Iterable[str]) -> str:
    """Search words as stored: lower-case, comma-separated, no repeats, at most 12."""
    parts = words.split(",") if isinstance(words, str) else list(words)
    kept: list[str] = []
    for part in parts:
        word = " ".join(part.lower().split())
        if word and word not in kept:
            kept.append(word)
    return ", ".join(kept[:KEYWORDS_LIMIT])


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
        self.places = Places(db)

    def prompt_facts(
        self, member: Member, message: str = "", earlier: Sequence[str] = ()
    ) -> tuple[list[str], list[str]]:
        """(pinned facts for the system prompt, notes retrieved for this message and
        their `earlier` messages)."""
        pinned, retrieved = self.for_prompt(member, message, earlier)
        places = self.places.mentioned(member, " ".join([message, *earlier]))  # F57b
        # F58e: the day the message names ("tomorrow"), so a place's line has its hours then.
        day = day_named(message, self._today(member)) if places else None
        lines = [p.line(day if p.hours else None) for p in places]
        return [f.fact for f in pinned], [f.fact for f in retrieved] + lines

    def _today(self, member: Member) -> date:
        row = self.db.one("SELECT timezone FROM family LIMIT 1")
        zone = ZoneInfo(str(row["timezone"]) if row and row["timezone"] else "UTC")
        return member_day(member, clock.now(), zone)

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
        keywords: str | Iterable[str] = "",
    ) -> Fact:
        subject, fact = subject.strip() or "general", fact.strip()
        words = keyword_text(keywords)
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
            if words:  # said again with new search words: keep both
                self.set_keywords(existing["id"], f"{existing['keywords']}, {words}")
            return self.get(existing["id"])
        now = to_utc_iso(clock.now())
        fact_id = self.db.execute(
            "INSERT INTO facts (scope, member_id, subject, fact, keywords, pinned, source, "
            "created_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (scope, member_id, subject, fact, words, int(pinned), source, member.id, now, now),
        )
        return self.get(fact_id)

    def pin(self, fact_id: int, pinned: bool = True) -> Fact:
        """Pinned by hand or by a repair: it isn't unpinned again for `UNPIN_AFTER`."""
        now = to_utc_iso(clock.now())
        self.db.execute(
            "UPDATE facts SET pinned = ?, updated_at = ?, unpinned_at = NULL, "
            "pinned_at = CASE WHEN ? THEN ? ELSE pinned_at END WHERE id = ?",
            (int(pinned), now, int(pinned), now, fact_id),
        )
        return self.get(fact_id)

    def unpin_idle(self) -> int:
        """F57b, the daily job: unpin each pinned fact that hasn't matched anything said or
        looked up for `UNPIN_AFTER` (counted from when it was pinned if it never has).
        Returns how many."""
        now = clock.now()
        cutoff = to_utc_iso(now - UNPIN_AFTER)
        rows = self.db.query(
            "SELECT id, subject FROM facts WHERE pinned = 1 "
            "AND max(coalesce(last_matched_at, ''), coalesce(pinned_at, created_at)) < ?",
            (cutoff,),
        )
        for row in rows:
            self.db.execute(
                "UPDATE facts SET pinned = 0, unpinned_at = ? WHERE id = ?",
                (to_utc_iso(now), row["id"]),
            )
            log.info(
                "Unpinned fact %s (%s): it hadn't come up in 8 weeks", row["id"], row["subject"]
            )
        return len(rows)

    def correct(self, fact_id: int, fact: str) -> Fact:
        self.db.execute(
            "UPDATE facts SET fact = ?, updated_at = ? WHERE id = ?",
            (fact.strip(), to_utc_iso(clock.now()), fact_id),
        )
        return self.get(fact_id)

    def set_keywords(self, fact_id: int, keywords: str | Iterable[str]) -> Fact:
        self.db.execute(
            "UPDATE facts SET keywords = ?, updated_at = ? WHERE id = ?",
            (keyword_text(keywords), to_utc_iso(clock.now()), fact_id),
        )
        return self.get(fact_id)

    def forget(self, fact_id: int) -> None:
        self.db.execute("DELETE FROM facts WHERE id = ?", (fact_id,))

    @staticmethod
    def can_edit(member: Member, fact: Fact) -> bool:
        """Anyone may edit household facts; personal facts only by their owner."""
        return fact.scope == "family" or fact.member_id == member.id

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

    def for_prompt(
        self, member: Member, message: str, earlier: Sequence[str] = ()
    ) -> tuple[list[Fact], list[Fact]]:
        """(pinned facts for the system prompt, retrieved notes for this turn), stamped as
        shown. The latest message's matches come first; `earlier` (their own last messages,
        F57a) only fill the places left."""
        pinned = self.pinned(member)
        retrieved = self.search(message, member)
        if pinned:  # F57b: which pinned facts this message is about, for unpinning idle ones
            said = " ".join([message, *earlier])
            matched = self.search(
                said, member, limit=len(pinned) + RETRIEVE_LIMIT, include_pinned=True
            )
            self._stamp_matched([f for f in matched if f.pinned])
        if earlier and len(retrieved) < RETRIEVE_LIMIT:
            seen = {f.id for f in retrieved}
            for fact in self.search(" ".join(earlier), member):
                if len(retrieved) >= RETRIEVE_LIMIT:
                    break
                if fact.id not in seen:
                    retrieved.append(fact)
                    seen.add(fact.id)
        self._stamp_shown([*pinned, *retrieved])
        self._stamp_matched(retrieved)
        return pinned, retrieved

    def lookup(self, member: Member, query: str, limit: int = LOOKUP_LIMIT) -> list[Fact]:
        """F57a, `search_memory`: facts this member may see, pinned or not, best first,
        stamped as shown."""
        found = self.search(query, member, limit=limit, include_pinned=True)
        self._stamp_shown(found)
        self._stamp_matched(found)
        return found

    def _stamp_matched(self, facts: Sequence[Fact]) -> None:
        matched = [f.id for f in facts]
        if matched:
            placeholders = ", ".join("?" for _ in matched)
            self.db.execute(
                f"UPDATE facts SET last_matched_at = ? WHERE id IN ({placeholders})",
                (to_utc_iso(clock.now()), *matched),
            )

    def _stamp_shown(self, facts: Sequence[Fact]) -> None:
        shown = [f.id for f in facts]
        if shown:
            placeholders = ", ".join("?" for _ in shown)
            self.db.execute(
                f"UPDATE facts SET last_shown_at = ? WHERE id IN ({placeholders})",
                (to_utc_iso(clock.now()), *shown),
            )

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


@tool(
    "remember_place",
    "Save a place they name instead of an address: 'when I say Stanford, take me to the "
    "visitor parking lot at 200 S Pasteur Dr', 'the in-laws' address is ...'. Saving one "
    "with the same name updates it. Travel and leave times use its address.",
    {
        "name": {"type": "string", "description": "What they call it, e.g. 'Stanford'."},
        "address": {
            "type": "string",
            "description": "Where to go when they say it (the parking lot's, if they said so).",
        },
        "aliases": {
            "type": "string",
            "description": "Other names for it, comma-separated, e.g. 'Stanford Hospital'. "
            "Empty if none.",
        },
        "note": {
            "type": "string",
            "description": "Worth knowing whenever they go, e.g. visiting or opening hours. "
            "Empty if none.",
        },
        "hours": {
            "type": "string",
            "description": "Its opening or visiting hours by day, as said, e.g. 'weekdays "
            "6:30-8:30 pm, weekends 12-8:30 pm' or 'Mon-Fri 9-5, Sat 10-2'. Empty if none were "
            "said (an empty one keeps what was saved).",
        },
        "arrive_early_minutes": {
            "type": "integer",
            "description": "Minutes before an event there they want to arrive (to park and "
            "walk in), 0 if they didn't say.",
        },
        "about": {
            "type": "string",
            "enum": ["household", "personal"],
            "description": "household for a shared place; personal for their own.",
        },
    },
)
async def remember_place(ctx: ToolContext, args: dict[str, Any]) -> str:
    memory = ctx.services.maybe(keys.memory)
    assert memory is not None
    said_hours = " ".join(str(args.get("hours") or "").split())
    try:
        hours = read_hours(said_hours) if said_hours else None  # F58e
        place = memory.places.save(
            ctx.member,
            str(args["name"]),
            str(args["address"]),
            aliases=str(args.get("aliases") or ""),
            note=str(args.get("note") or ""),
            arrive_early=int(args.get("arrive_early_minutes") or 0),
            scope="member" if args.get("about") == "personal" else "family",
            hours=hours,
        )
    except ValueError as exc:
        raise ToolFailed(f"Nothing was saved: {exc}.") from exc
    return f"Remembered. {place.line()}"


# CR8a: the system prompt's rules about this module's feature.
PROMPT_RULES = (
    PromptFragment(
        "memory.remember-that-the-bins",
        "act",
        70,
        """\
- "Remember that the bins go out on Wednesday nights" tells you a fact: remember_fact.
  Make it a task with reminders only when they ask to be reminded ("remind me...").
  Give it keywords: other words someone might use when it matters (people, places, what
  it's for), so it comes up when they don't use the same words.""",
    ),
    PromptFragment(
        "memory.search-memory",
        "act",
        75,
        """\
- Before saying you don't know something they may have told you (a place, opening or
  visiting hours, someone's preference), look with search_memory.""",
    ),
    PromptFragment(
        "memory.remember-place",
        "act",
        76,
        """\
- "When I say Stanford, take me to the parking lot at ..." or "X's address is ..." is a
  place: remember_place, with its hours by day in hours and how early they like to
  arrive. "X's hours are ..." for a saved place X: remember_place with the same name and
  address and those hours. For an event at a saved place, use its address as the event's
  location, and keep to that day's hours (weekdays and weekends can differ).""",
    ),
    PromptFragment(
        "memory.after-answering-a-general",
        "act",
        160,
        """\
- After answering a general question worth keeping ("what age can babies face forward in a
  carrier?"), keep a one-line note of the answer with remember_fact.""",
    ),
)


class MemoryModule(Module):
    """Facts Themi was told, recalled when they matter."""

    name = "memory"
    title = "Memory"
    group = BEHIND_THE_SCENES
    summary = "Remembers what it's told and brings it up when it matters."

    def install(self, ctx: ModuleContext) -> None:
        from themi.core.rules import Rulebook  # at install: importing it at the top is a cycle
        from themi.modules.web import MenuEntry
        from themi.web import icons, knowledge_pages

        ctx.prompt(*PROMPT_RULES)
        ctx.web(
            knowledge_pages.routes,
            MenuEntry(
                "/knowledge",
                "Rules & memory",
                "What Themi keeps to and remembers",
                "Household",
                10,
                bar_label="Rules",
                icon=icons.KNOWLEDGE,
            ),
        )
        memory = ctx.provide(Memory(ctx.services.store.db, ctx.get(Rulebook)))
        ctx.services.facts_source = memory.prompt_facts
        ctx.tool(remember_place)  # F57b

        async def unpin_idle() -> int:
            return memory.unpin_idle()

        ctx.periodic("memory.unpin_idle", timedelta(days=1), unpin_idle)
