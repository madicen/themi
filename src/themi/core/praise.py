"""A warm word for something done (F19b, Erin's idea #102): tasks and routine items.

Done in Themi (a tap, a tick, in chat), the word goes in the reply or the edit. Ticked on the
wall, by someone the wall names, it's a message of its own a moment later, so ticks close
together go as one. It goes when it's news, quiet hours or not (`Outbox`, PRAISE_KIND), and
is dropped if it can't go while it is. Praise for what's done, never a nudge for more.
"""

from __future__ import annotations

import secrets
import zlib
from datetime import timedelta
from typing import Any

from themi import clock
from themi.accounts import Member
from themi.channels.outbox import PRAISE_KIND, Outbox, Priority

PRAISE = ("Nice work.", "Well done.", "Good job.", "Nicely done.", "That's one off the list.")
WALL_DONE_TEXT = "Ticked off on the wall: {titles}. {praise}"
WALL_PRAISE_AFTER = timedelta(minutes=1)
WALL_PRAISE_USEFUL = timedelta(hours=2)


def word(seed: str) -> str:
    """One of PRAISE, varied by what was done and the moment, so it doesn't read as a stamp."""
    return PRAISE[zlib.crc32(f"{seed}-{clock.now():%Y%m%d%H%M}".encode()) % len(PRAISE)]


async def from_wall(outbox: Outbox, member: Member, title: str, seed: str) -> None:
    """Ticked on the wall by `member`: a warm word, a moment later, if they want one."""
    if not member.done_praise or member.telegram_user_id is None:
        return
    now = clock.now()
    await outbox.send(
        member,
        WALL_DONE_TEXT.format(titles=title, praise=word(seed)),
        priority=Priority.NORMAL,
        kind=PRAISE_KIND,
        not_before=now + WALL_PRAISE_AFTER,
        expires=now + WALL_PRAISE_USEFUL,
        dedupe_key=f"praise-{seed}-{secrets.token_hex(4)}",
    )


def install(outbox: Outbox) -> None:
    async def together(member: Member, rows: list[dict[str, Any]]) -> bool:
        """Several ticks on the wall at once: one warm word for them all, tasks in the order
        they were made, then routine items."""
        rows = sorted(rows, key=_order)
        titles = [_title(str(r["text"])) for r in rows]
        joined = f"{', '.join(titles[:-1])} and {titles[-1]}"
        seed = _seed(rows[0])
        result = await outbox.send(
            member,
            WALL_DONE_TEXT.format(titles=joined, praise=word(seed)),
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


def _title(text: str) -> str:
    """What a queued warm word is about: WALL_DONE_TEXT read back."""
    prefix = WALL_DONE_TEXT.split("{")[0]
    body = text.removeprefix(prefix)
    for each in PRAISE:
        if body.endswith(f". {each}"):
            return body.removesuffix(f". {each}")
    return body
