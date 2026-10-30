"""What lands with each person, from their reactions (S5, Erin's idea #31).

A 👍 ❤️ or 🙏 on one of Themi's messages counts as good, a 👎 or 😕 as not,
recorded with what kind of message it was (a nudge, a check-in, a summary, a
chat reply, a heads-up) and how long. Approval cards are left out: a reaction
there answers the card. A later reaction on the same message replaces the
earlier one.

Over time that becomes a line in words ("short nudges do well; long
summaries don't"), for the model and for the person's My week page. The
"reactions" switch, like the other inputs, stops both the recording and the line.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from typing import Any

from themi import clock
from themi.accounts import Member
from themi.channels.events import InboundEvent
from themi.core.groceries import and_list
from themi.core.services import Services
from themi.localtime import to_utc_iso

GOOD = frozenset({"👍", "❤", "❤️", "🙏"})
NOT_GOOD = frozenset({"👎", "😕"})
CARDS = ("approval", "rule")  # a reaction there is an answer, not a judgement
KIND_WORDS = {
    "chat": "chat replies",
    "task": "nudges",
    "reminder": "nudges",
    "habit": "nudges",
    "routine": "check-ins",
    "review": "check-ins",
    "summary": "summaries",
    "task_summary": "summaries",
    "email_audit": "summaries",
}
OTHER = "heads-ups"
SHORT, MEDIUM = 160, 500  # characters: up to a couple of lines, up to a short paragraph
LOOK_BACK = timedelta(days=90)
ENOUGH = 3  # reactions before a kind of message says anything
DOES_WELL = 2 / 3  # this share good or more
DOESNT = 1 / 2  # this share not good or more


def length_word(text: str) -> str:
    size = len(text)
    return "short" if size <= SHORT else "medium-length" if size <= MEDIUM else "long"


def verdict(emoji: tuple[str, ...]) -> int:
    """+1 good, -1 not, 0 neither (the first that counts wins)."""
    for e in emoji:
        if e in GOOD:
            return 1
        if e in NOT_GOOD:
            return -1
    return 0


class Reactions:
    def __init__(self, services: Services) -> None:
        self.services = services
        self.db = services.store.db

    def install(self) -> None:
        self.services.reaction_handlers.append(self.on_reaction)
        self.services.reactions = self

    async def on_reaction(self, event: InboundEvent) -> None:
        assert event.reaction is not None
        member = event.member
        value = verdict(event.reaction.added)
        if value == 0 or not member.tracks("reactions"):
            return
        row = self.db.one(
            "SELECT * FROM outbox WHERE member_id = ? AND telegram_message_id = ? "
            "AND status = 'sent' ORDER BY id DESC LIMIT 1",
            (member.id, event.reaction.message_id),
        )
        if row is None or row["kind"] in CARDS:
            return
        self.db.execute(
            "INSERT INTO message_reactions (member_id, outbox_id, kind, length, value, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(member_id, outbox_id) DO UPDATE SET "
            "value = excluded.value, created_at = excluded.created_at",
            (
                member.id,
                row["id"],
                self._kind(row),
                length_word(row["sent_text"] or row["text"]),
                value,
                to_utc_iso(clock.now()),
            ),
        )

    def picture(self, member: Member) -> str:
        """What lands, in words: "" while there's too little to say, or it's switched off."""
        if not member.tracks("reactions"):
            return ""
        rows = self.db.query(
            "SELECT kind, length, value FROM message_reactions WHERE member_id = ? "
            "AND created_at >= ?",
            (member.id, to_utc_iso(clock.now() - LOOK_BACK)),
        )
        by_both: dict[tuple[str, str], list[int]] = defaultdict(list)
        by_kind: dict[str, list[int]] = defaultdict(list)
        for row in rows:
            by_both[(row["length"], row["kind"])].append(row["value"])
            by_kind[row["kind"]].append(row["value"])
        well, not_well = [], []
        said = set()
        for (length, kind), values in sorted(by_both.items(), key=lambda kv: -len(kv[1])):
            if (lean := _lean(values)) is not None:
                (well if lean > 0 else not_well).append(f"{length} {kind}")
                said.add(kind)
        for kind, values in sorted(by_kind.items(), key=lambda kv: -len(kv[1])):
            if kind not in said and (lean := _lean(values)) is not None:
                (well if lean > 0 else not_well).append(kind)
        parts = []
        if well:
            parts.append(f"{and_list(well)} do well")
        if not_well:
            parts.append(f"{and_list(not_well)} don't")
        return "; ".join(parts)

    def _kind(self, row: dict[str, Any]) -> str:
        kind = str(row["kind"])
        if kind == "chat" and row["priority"] != "reply":
            return OTHER
        if kind == "task" and str(row["dedupe_key"] or "").startswith("task-"):
            task_id = str(row["dedupe_key"]).split("-")[1]
            task = self.db.one("SELECT check_in FROM tasks WHERE id = ?", (task_id,))
            if task is not None and task["check_in"]:
                return "check-ins"
        return KIND_WORDS.get(kind, OTHER)


def _lean(values: list[int]) -> int | None:
    if len(values) < ENOUGH:
        return None
    good = sum(1 for v in values if v > 0) / len(values)
    if good >= DOES_WELL:
        return 1
    if 1 - good >= DOESNT:
        return -1
    return None
