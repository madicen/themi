"""A warm word for something done (F19b, Erin's idea #102): tasks and routine items.

Done in Themi (a tap, a tick, in chat), the word goes in the reply or the edit. Ticked on a
display that keeps Themi's tasks or routines (a mirror, CR21b), by someone it names, it's a
message of its own a moment later, so ticks close together go as one. It goes when it's
news, quiet hours or not (`Outbox`, PRAISE_KIND), and is dropped if it can't go while it
is. Praise for what's done, never a nudge for more.
"""

from __future__ import annotations

import secrets
import zlib
from datetime import timedelta
from typing import Any, ClassVar

from themi import clock
from themi.accounts import Member
from themi.accounts.preferences import Preferences
from themi.channels.outbox import PRAISE_KIND, Outbox, Priority

PRAISE = ("Nice work.", "Well done.", "Good job.", "Nicely done.", "That's one off the list.")
DONE_THERE_TEXT = "Ticked off {where}: {titles}. {praise}"  # where: the mirror's ("on ...")
PRAISE_AFTER = timedelta(minutes=1)
PRAISE_USEFUL = timedelta(hours=2)


class TasksPreferences(Preferences):
    """CR7b1: a short warm word when they mark a task done (idea #102)."""

    module: ClassVar[str] = "tasks"
    done_praise: bool = True


def word(seed: str) -> str:
    """One of PRAISE, varied by what was done and the moment, so it doesn't read as a stamp."""
    return PRAISE[zlib.crc32(f"{seed}-{clock.now():%Y%m%d%H%M}".encode()) % len(PRAISE)]


async def ticked_there(outbox: Outbox, member: Member, title: str, seed: str, where: str) -> None:
    """Ticked by `member` on a mirror (`where`: "on ..."): a warm word, a moment later, if
    they want one."""
    if (
        not outbox.store.preferences(member.id, TasksPreferences).done_praise
        or not member.reachable
    ):
        return
    now = clock.now()
    await outbox.send(
        member,
        DONE_THERE_TEXT.format(where=where, titles=title, praise=word(seed)),
        priority=Priority.NORMAL,
        kind=PRAISE_KIND,
        not_before=now + PRAISE_AFTER,
        expires=now + PRAISE_USEFUL,
        dedupe_key=f"praise-{seed}-{secrets.token_hex(4)}",
    )


def install(outbox: Outbox) -> None:
    async def together(member: Member, rows: list[dict[str, Any]]) -> bool:
        """Several ticks on a mirror at once: one warm word for them all, tasks in the order
        they were made, then routine items."""
        rows = sorted(rows, key=_order)
        titles = [_title(str(r["text"])) for r in rows]
        joined = f"{', '.join(titles[:-1])} and {titles[-1]}"
        seed = _seed(rows[0])
        where = _where(str(rows[0]["text"]))
        result = await outbox.send(
            member,
            DONE_THERE_TEXT.format(where=where, titles=joined, praise=word(seed)),
            priority=Priority.NORMAL,
            kind=PRAISE_KIND,
            deadline=clock.now(),
        )
        if result.outbox_id is None:
            return False
        for row in rows:
            outbox.cancel(row["id"])
        return True

    outbox.bundlers[PRAISE_KIND] = together


def _seed(row: dict[str, Any]) -> str:
    """What a queued warm word is for: a task's id, or "r" and a routine item's."""
    return str(row["dedupe_key"]).split("-")[1]


def _order(row: dict[str, Any]) -> tuple[bool, int]:
    seed = _seed(row)
    return seed.startswith("r"), int(seed.removeprefix("r"))


def _where(text: str) -> str:
    """Where a queued warm word's tick was: DONE_THERE_TEXT read back."""
    head = text.split(": ", 1)[0]
    return head.removeprefix(DONE_THERE_TEXT.split("{")[0])


def _title(text: str) -> str:
    """What a queued warm word is about: DONE_THERE_TEXT read back."""
    body = text.split(": ", 1)[1] if ": " in text else text
    for each in PRAISE:
        if body.endswith(f". {each}"):
            return body.removesuffix(f". {each}")
    return body
