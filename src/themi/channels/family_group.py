"""The family group (34b): one Telegram group both partners are in, with Themi.

An admin adds the bot to a group and sends /familygroup there; that links it (and
"/familygroup off" unlinks it). In the linked group, Themi reads only family members'
messages, and only those meant for it: a command, a mention of the bot, or a Reply to one
of its messages. Everything else said there (the partners talking to each other, anyone
outside the family) is left alone and never logged.

A message said to Themi in the group is answered in the group: while it's handled,
`group_replies` holds the speaker's member id, and the outbox sends that person's replies
to the group instead of their own chat. A question for the family (an alignment prompt) is
sent to the group on purpose (`Outbox.send(..., to_group=True)`), and waits until everyone
is free and predicted receptive.

Everyone in the group reads what goes there, so it's shielded with the stricter partner's
settings (`shared_reader`): shielding on if anyone has it on, the highest strength, gentle
phrasing if anyone likes it gentle. Model calls for it run on the backend of the person
it's for (the owner), as shared tasks do.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, replace
from datetime import datetime

from themi import clock
from themi.accounts import Member
from themi.localtime import to_utc_iso
from themi.storage.db import Database

# The member whose replies go to the family group, while their group message is handled.
group_replies: ContextVar[int | None] = ContextVar("group_replies", default=None)


@dataclass(frozen=True)
class LinkedGroup:
    chat_id: int
    title: str
    linked_by: int | None
    linked_at: datetime


class FamilyGroup:
    def __init__(self, db: Database) -> None:
        self.db = db

    def get(self) -> LinkedGroup | None:
        row = self.db.one("SELECT * FROM family_group WHERE id = 1")
        if row is None:
            return None
        return LinkedGroup(
            row["chat_id"], row["title"], row["linked_by"], datetime.fromisoformat(row["linked_at"])
        )

    def chat_id(self) -> int | None:
        return self.db.scalar("SELECT chat_id FROM family_group WHERE id = 1")

    def is_family(self, chat_id: int) -> bool:
        return self.chat_id() == chat_id

    def link(self, chat_id: int, title: str, by: Member) -> None:
        self.db.execute(
            "INSERT INTO family_group (id, chat_id, title, linked_by, linked_at) "
            "VALUES (1, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET chat_id = excluded.chat_id, "
            "title = excluded.title, linked_by = excluded.linked_by, "
            "linked_at = excluded.linked_at",
            (chat_id, title[:200], by.id, to_utc_iso(clock.now())),
        )

    def unlink(self) -> bool:
        return bool(self.db.update("DELETE FROM family_group WHERE id = 1"))

    def moved(self, old_chat_id: int, new_chat_id: int) -> bool:
        """Telegram made the group a supergroup: same group, a new chat id."""
        return bool(
            self.db.update(
                "UPDATE family_group SET chat_id = ? WHERE chat_id = ?",
                (new_chat_id, old_chat_id),
            )
        )


def replies_to_group(member: Member) -> bool:
    """Is this member's reply, right now, going to the family group?"""
    return group_replies.get() == member.id


def shared_reader(owner: Member, members: list[Member]) -> Member:
    """Who a group message is shielded for: the owner (whose AI backend rewrites it), with
    the strictest PDA settings of everyone in the group."""
    readers = [m for m in members if m.telegram_user_id is not None] or [owner]
    shielded = [m for m in readers if m.pda_enabled]
    notes = "; ".join(dict.fromkeys(m.phrasing_notes for m in readers if m.phrasing_notes))
    return replace(
        owner,
        pda_enabled=bool(shielded),
        pda_strength=max((m.pda_strength for m in shielded), default=owner.pda_strength),
        phrasing="gentle" if any(m.phrasing == "gentle" for m in readers) else owner.phrasing,
        phrasing_notes=notes,
    )
