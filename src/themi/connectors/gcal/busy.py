"""Busy blocks from each person's primary Google calendar (S2).

Every 15 minutes, for each linked account with calendar access, the next week of
the primary calendar is read. Only the start and end of busy events are kept:
never titles, attendees or anything else. All-day events, events shown as free,
cancelled ones and invitations the person declined are left out.

The blocks hold Themi's own messages (like busy times) and feed the Shadow
Calendar. A person can switch the "calendar" input off; their blocks are then
deleted and nothing more is read. If Google can't be reached, the last blocks
are kept.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from themi import clock
from themi.accounts import AccountStore, Member
from themi.connectors.gcal.sync import CalendarSync
from themi.connectors.google import CALENDAR_SCOPE
from themi.localtime import to_utc_iso

log = logging.getLogger(__name__)

LOOK_AHEAD = timedelta(days=7)


def _busy(event: dict[str, Any]) -> tuple[datetime, datetime] | None:
    """The event's start and end, if it's a timed event that makes the person busy."""
    if event.get("status") == "cancelled" or event.get("transparency") == "transparent":
        return None
    start, end = event.get("start", {}), event.get("end", {})
    if "dateTime" not in start or "dateTime" not in end:
        return None  # all-day events don't block particular hours
    for attendee in event.get("attendees", []):
        if attendee.get("self") and attendee.get("responseStatus") == "declined":
            return None
    begins = datetime.fromisoformat(start["dateTime"].replace("Z", "+00:00"))
    ends = datetime.fromisoformat(end["dateTime"].replace("Z", "+00:00"))
    return (begins, ends) if ends > begins else None


class CalendarBusy:
    def __init__(self, store: AccountStore, sync: CalendarSync) -> None:
        self.store = store
        self.db = store.db
        self.sync = sync

    async def refresh(self) -> int:
        """Scheduler job: re-read everyone's next week. Returns how many accounts were read."""
        read = 0
        now = clock.now()
        for member in self.store.list_members():
            if not member.tracks("calendar"):
                self.db.execute("DELETE FROM calendar_busy WHERE member_id = ?", (member.id,))
                continue
            for account in self.store.linked_accounts(member.id):
                if not account.enabled or not account.allows(CALENDAR_SCOPE):
                    continue
                try:
                    events = await self.sync.client(account.id).list_events(
                        "primary", to_utc_iso(now), to_utc_iso(now + LOOK_AHEAD)
                    )
                except Exception as exc:  # keep what we knew; try again next time
                    log.warning(
                        "Couldn't read the calendar for account %s (%s)",
                        account.id,
                        type(exc).__name__,
                    )
                    continue
                blocks = [b for e in events if (b := _busy(e)) is not None]
                with self.db.transaction():
                    self.db.execute("DELETE FROM calendar_busy WHERE account_id = ?", (account.id,))
                    for begins, ends in blocks:
                        self.db.execute(
                            "INSERT INTO calendar_busy (member_id, account_id, starts_at, "
                            "ends_at, fetched_at) VALUES (?, ?, ?, ?, ?)",
                            (member.id, account.id, to_utc_iso(begins), to_utc_iso(ends),
                             to_utc_iso(now)),
                        )  # fmt: skip
                read += 1
        return read

    def blocks(
        self, member: Member, start: datetime, end: datetime
    ) -> list[tuple[datetime, datetime]]:
        """Busy blocks overlapping [start, end), soonest first."""
        if not member.tracks("calendar"):
            return []
        rows = self.db.query(
            "SELECT starts_at, ends_at FROM calendar_busy WHERE member_id = ? "
            "AND ends_at > ? AND starts_at < ? ORDER BY starts_at",
            (member.id, to_utc_iso(start), to_utc_iso(end)),
        )
        return [
            (datetime.fromisoformat(r["starts_at"]), datetime.fromisoformat(r["ends_at"]))
            for r in rows
        ]
