"""Pausing kinds of proactive messages ("no meal reminders today").

A pause holds matching messages in the outbox until it ends; nothing is
dropped. Replies and urgent alerts are never paused: someone saying "pause
everything" still hears back, and still hears about a burst pipe.

Topics map onto outbox message kinds. Features tag what they send with a
kind ("meal", "laundry", ...) and add it to a topic here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from themi import clock
from themi.accounts import Member
from themi.localtime import next_waking_start, start_of_local_day, to_utc_iso
from themi.storage.db import Database

EVERYTHING = "everything"
TOPICS: dict[str, frozenset[str]] = {
    "meals": frozenset({"meal"}),
    "laundry": frozenset({"laundry"}),
    "vacuum": frozenset({"vacuum"}),
    "feeders": frozenset({"feeder"}),
    "litter": frozenset({"litter_box"}),
    "maintenance": frozenset({"maintenance"}),
    "tasks": frozenset({"task", "task_summary"}),
    "habits": frozenset({"habit", "routine", "review"}),
    "approvals": frozenset({"approval", "rule"}),
    # notes passed on from your partner, and questions for you both (34b)
    "notes": frozenset({"relay", "alignment"}),
    # B1; EX2b: questions about expense sheets wait out a break too (a break is rest)
    "break": frozenset(
        {"task", "task_summary", "habit", "routine", "review", "expense", "expense_review"}
    ),
    # RC3b: while cooking with Themi, nudges and check-ins wait; replies, approvals, urgent
    # alerts and their own timers still come.
    "cooking": frozenset(
        {"task", "task_summary", "habit", "routine", "review", "expense", "expense_review"}
    ),
    # BD1a: while someone keeps them company on a job, the same wait as a break.
    "body_double": frozenset(
        {"task", "task_summary", "habit", "routine", "review", "expense", "expense_review"}
    ),
    # F22d: whatever asks something of them; replies, urgent alerts, their own reminders,
    # meals and travel heads-ups still come. F42b (Erin, bug #204): a time-sensitive email
    # alert (`normal`) waits too; an urgent one is `urgent`, which no pause holds.
    "burnout": frozenset(
        {
            "email",
            "task",
            "task_summary",
            "habit",
            "routine",
            "review",
            "focus",
            "summary",
            "approval",
            "rule",
            "email_audit",
            "laundry",
            "vacuum",
            "feeder",
            "litter_box",
            "maintenance",
            "takeout",
            "safeway",
            "alignment",
            "expense",  # EX2b
            "expense_review",
            "someday",  # F36b
        }
    ),
    EVERYTHING: frozenset(),  # every proactive message
}
TOPIC_WORDS = {
    "meals": "meal reminders",
    "laundry": "laundry nudges",
    "vacuum": "vacuum nudges",
    "feeders": "feeder nudges",
    "litter": "litter box nudges",
    "maintenance": "maintenance reminders",
    "tasks": "task nudges",
    "habits": "check-ins",
    "approvals": "approval requests",
    "notes": "notes from your partner and questions for you both",
    "break": "task nudges and check-ins, for a break",
    "body_double": "task nudges and check-ins, while I keep you company",
    "burnout": "everything that asks something of you, for burnout mode",
    EVERYTHING: "everything that can wait",
}
ALIASES = {
    "meal": "meals",
    "food": "meals",
    "eating": "meals",
    "lunch": "meals",
    "dinner": "meals",
    "washer": "laundry",
    "dryer": "laundry",
    "roborock": "vacuum",
    "robot": "vacuum",
    "feeder": "feeders",
    "catgenie": "litter",
    "chores": "tasks",
    "task": "tasks",
    "habit": "habits",
    "checkins": "habits",
    "check-ins": "habits",
    "approval": "approvals",
    "all": EVERYTHING,
    "messages": EVERYTHING,
    "reminders": EVERYTHING,
    "relays": "notes",
}
MAX_PAUSE = timedelta(days=30)


class PauseError(ValueError):
    """A pause request that couldn't be understood; the message is safe to show."""


@dataclass(frozen=True)
class Pause:
    id: int
    topic: str
    until: datetime


def normalise_topic(word: str) -> str:
    topic = ALIASES.get(word.strip().lower(), word.strip().lower())
    if topic not in TOPICS:
        known = ", ".join(sorted(TOPICS))
        raise PauseError(f"I don't have a topic called {word!r}. Topics: {known}.")
    return topic


def parse_until(text: str, member: Member, timezone: str, now: datetime) -> datetime:
    """'today' (default), 'tonight', 'tomorrow', '3h', '2 hours', '3d', 'a week'."""
    phrase = text.strip().lower().removeprefix("for ").strip()
    if phrase in ("", "today", "for today", "the day", "rest of today"):
        return start_of_local_day(now, timezone) + timedelta(days=1)
    if phrase in ("tonight", "this evening"):
        return next_waking_start(member, now, timezone)
    if phrase in ("tomorrow", "until tomorrow night"):
        return start_of_local_day(now, timezone) + timedelta(days=2)
    if phrase in ("a week", "1 week", "the week", "week"):
        return now + timedelta(days=7)
    match = re.fullmatch(r"(an?|\d+)\s*(h|hr|hrs|hours?|d|days?|w|weeks?|m|mins?|minutes?)", phrase)
    if not match:
        raise PauseError(
            f"I didn't catch how long {text!r} is. Try 'today', 'tonight', '3 hours' or '2 days'."
        )
    amount = 1 if match[1] in ("a", "an") else int(match[1])
    unit = match[2][0]
    delta = {
        "h": timedelta(hours=amount),
        "d": timedelta(days=amount),
        "w": timedelta(weeks=amount),
        "m": timedelta(minutes=amount),
    }[unit]
    if delta <= timedelta(0) or delta > MAX_PAUSE:
        raise PauseError("A pause can run from a few minutes up to 30 days.")
    return now + delta


class PauseBook:
    def __init__(self, db: Database) -> None:
        self.db = db

    def pause(self, member: Member, topic: str, until: datetime) -> Pause:
        topic = normalise_topic(topic)
        pause_id = self.db.execute(
            "INSERT INTO pauses (member_id, topic, until, created_at) VALUES (?, ?, ?, ?)",
            (member.id, topic, to_utc_iso(until), to_utc_iso(clock.now())),
        )
        return Pause(pause_id, topic, until)

    def resume(self, member: Member, topic: str | None = None) -> int:
        """End matching pauses now (all of them when `topic` is None). Returns how many."""
        now = to_utc_iso(clock.now())
        if topic is None:
            return self.db.update(
                "UPDATE pauses SET ended_at = ? WHERE member_id = ? AND ended_at IS NULL "
                "AND until > ?",
                (now, member.id, now),
            )
        return self.db.update(
            "UPDATE pauses SET ended_at = ? WHERE member_id = ? AND topic = ? "
            "AND ended_at IS NULL AND until > ?",
            (now, member.id, normalise_topic(topic), now),
        )

    def move(self, pause_id: int, until: datetime) -> None:
        """Change when a pause still going on ends (a session that runs longer, BD1a)."""
        self.db.execute(
            "UPDATE pauses SET until = ? WHERE id = ? AND ended_at IS NULL",
            (to_utc_iso(until), pause_id),
        )

    def active(self, member: Member) -> list[Pause]:
        rows = self.db.query(
            "SELECT id, topic, until FROM pauses WHERE member_id = ? AND ended_at IS NULL "
            "AND until > ? ORDER BY until",
            (member.id, to_utc_iso(clock.now())),
        )
        return [Pause(r["id"], r["topic"], datetime.fromisoformat(r["until"])) for r in rows]

    def held_until(self, member: Member, kind: str) -> datetime | None:
        """When a proactive message of `kind` may go out, if a pause is holding it."""
        covering = [
            p.until for p in self.active(member) if p.topic == EVERYTHING or kind in TOPICS[p.topic]
        ]
        return max(covering) if covering else None
