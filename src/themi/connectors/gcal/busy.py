"""Each person's own calendars: busy blocks (S2) and, since K1, what's on them.

Every 15 minutes, for each linked account with calendar access, the calendars the
person chose (the primary one if they haven't) are read for the next two weeks.
What's kept, per event: its title, place, start and end, whether it's all day and
whether it's a video call, and which of Themi's own events it is. Never
descriptions or attendees: what others write into an invitation is the riskiest
text there is. Cancelled events and invitations the person declined are left out.

- Busy blocks: timed events that aren't shown as free. Themi's blocks of time for
  a task (K5, `TASK_BLOCK`) aren't busy time, or they'd hold back that task's own
  nudge. The blocks hold Themi's messages (like busy times) and feed the Shadow
  Calendar.
- Details: the next two days reach the model as data from outside, in a delimited
  block, only in conversations the owner's setting allows ("calendar_details":
  just them, or their partner too).

A person can switch the "calendar" input off; their blocks and events are then
deleted and nothing more is read. If Google can't be reached, the last read is kept.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from themi import clock
from themi.accounts import AccountStore, Member
from themi.connectors.gcal.sync import CalendarSync
from themi.connectors.google import CALENDAR_SCOPE
from themi.core.prompts import as_data
from themi.localtime import to_utc_iso

log = logging.getLogger(__name__)

LOOK_AHEAD = timedelta(days=14)
CONTEXT_DAYS = 2  # today and tomorrow, for the model
TASK_BLOCK = "task-block:"  # K5: time Themi blocked for a task; never busy
MAX_TEXT = 200
VIDEO = re.compile(r"https?://\S*(?:zoom\.us|meet\.google\.com|teams\.microsoft\.com)", re.I)


@dataclass(frozen=True)
class Entry:
    member_id: int
    title: str
    location: str
    starts_at: datetime
    ends_at: datetime
    all_day: bool
    video: bool
    source: str | None  # set for Themi's own events ("task:12")


def _when(value: dict[str, Any], tz: ZoneInfo) -> tuple[datetime, bool] | None:
    if "dateTime" in value:
        return datetime.fromisoformat(value["dateTime"].replace("Z", "+00:00")), False
    if "date" in value:
        day = date.fromisoformat(value["date"])
        return datetime(day.year, day.month, day.day, tzinfo=tz), True
    return None


def _entry(event: dict[str, Any], tz: ZoneInfo) -> dict[str, Any] | None:
    """What's kept of an event, or None if it's not on the person's calendar any more."""
    if event.get("status") == "cancelled":
        return None
    for attendee in event.get("attendees", []):
        if attendee.get("self") and attendee.get("responseStatus") == "declined":
            return None
    begins, ends = _when(event.get("start", {}), tz), _when(event.get("end", {}), tz)
    if begins is None or ends is None or ends[0] <= begins[0]:
        return None
    location = " ".join(str(event.get("location") or "").split())[:MAX_TEXT]
    source = (event.get("extendedProperties") or {}).get("private", {}).get("themi")
    all_day = begins[1]
    return {
        "event_id": str(event.get("id", "")),
        "title": " ".join(str(event.get("summary") or "(no title)").split())[:MAX_TEXT],
        "location": location,
        "starts_at": begins[0],
        "ends_at": ends[0],
        "all_day": all_day,
        "video": bool(
            event.get("hangoutLink") or event.get("conferenceData") or VIDEO.search(location)
        ),
        "busy": not all_day
        and event.get("transparency") != "transparent"
        and not str(source or "").startswith(TASK_BLOCK),
        "source": str(source) if source else None,
    }


class CalendarBusy:
    def __init__(self, store: AccountStore, sync: CalendarSync) -> None:
        self.store = store
        self.db = store.db
        self.sync = sync

    # ----- reading Google ---------------------------------------------------------------

    async def refresh(self) -> int:
        """Scheduler job: re-read everyone's next two weeks. Returns how many accounts were
        read."""
        read = 0
        now = clock.now()
        tz = self._tz()
        for member in self.store.list_members():
            if not member.tracks("calendar"):
                self.db.execute("DELETE FROM calendar_busy WHERE member_id = ?", (member.id,))
                self.db.execute("DELETE FROM calendar_entries WHERE member_id = ?", (member.id,))
                continue
            for account in self.store.linked_accounts(member.id):
                if not account.enabled or not account.allows(CALENDAR_SCOPE):
                    continue
                client = self.sync.client(account.id)
                found: list[tuple[str, dict[str, Any]]] = []
                try:
                    for calendar_id, _ in self.calendars(account.id):
                        events = await client.list_events(
                            calendar_id, to_utc_iso(now), to_utc_iso(now + LOOK_AHEAD)
                        )
                        found += [(calendar_id, e) for ev in events if (e := _entry(ev, tz))]
                except Exception as exc:  # keep what we knew; try again next time
                    log.warning(
                        "Couldn't read the calendar for account %s (%s)",
                        account.id,
                        type(exc).__name__,
                    )
                    continue
                self._keep(member, account.id, found, now)
                read += 1
        return read

    def _keep(
        self,
        member: Member,
        account_id: int,
        found: list[tuple[str, dict[str, Any]]],
        now: datetime,
    ) -> None:
        stamp = to_utc_iso(now)
        with self.db.transaction():
            self.db.execute("DELETE FROM calendar_busy WHERE account_id = ?", (account_id,))
            self.db.execute("DELETE FROM calendar_entries WHERE account_id = ?", (account_id,))
            self.db.execute(
                "INSERT INTO calendar_reads (account_id, member_id, read_at) VALUES (?, ?, ?) "
                "ON CONFLICT(account_id) DO UPDATE SET read_at = excluded.read_at",
                (account_id, member.id, stamp),
            )
            for calendar_id, e in found:
                self.db.execute(
                    "INSERT INTO calendar_entries (member_id, account_id, calendar_id, event_id, "
                    "title, location, starts_at, ends_at, all_day, video, busy, source, "
                    "fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        member.id, account_id, calendar_id, e["event_id"], e["title"],
                        e["location"], to_utc_iso(e["starts_at"]), to_utc_iso(e["ends_at"]),
                        int(e["all_day"]), int(e["video"]), int(e["busy"]), e["source"], stamp,
                    ),
                )  # fmt: skip
                if e["busy"]:
                    self.db.execute(
                        "INSERT INTO calendar_busy (member_id, account_id, starts_at, "
                        "ends_at, fetched_at) VALUES (?, ?, ?, ?, ?)",
                        (member.id, account_id, to_utc_iso(e["starts_at"]),
                         to_utc_iso(e["ends_at"]), stamp),
                    )  # fmt: skip

    # ----- which calendars ----------------------------------------------------------------

    def calendars(self, account_id: int) -> list[tuple[str, str]]:
        """(id, name) of the calendars read for an account: the chosen ones, else primary."""
        rows = self.db.query(
            "SELECT calendar_id, name FROM member_calendars WHERE account_id = ? ORDER BY name",
            (account_id,),
        )
        return [(r["calendar_id"], r["name"]) for r in rows] or [("primary", "primary")]

    def choose(self, account_id: int, chosen: list[tuple[str, str]]) -> None:
        """The calendars to read for an account; none chosen means the primary one."""
        with self.db.transaction():
            self.db.execute("DELETE FROM member_calendars WHERE account_id = ?", (account_id,))
            for calendar_id, name in chosen:
                self.db.execute(
                    "INSERT INTO member_calendars (account_id, calendar_id, name) VALUES (?, ?, ?)",
                    (account_id, calendar_id, name[:MAX_TEXT]),
                )

    # ----- for the rest of Themi ----------------------------------------------------------

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

    def entries(self, member: Member, start: datetime, end: datetime) -> list[Entry]:
        """A person's events overlapping [start, end), soonest first."""
        if not member.tracks("calendar"):
            return []
        rows = self.db.query(
            "SELECT * FROM calendar_entries WHERE member_id = ? AND ends_at > ? AND starts_at < ? "
            "ORDER BY starts_at, all_day DESC, id",
            (member.id, to_utc_iso(start), to_utc_iso(end)),
        )
        return [
            Entry(
                r["member_id"],
                r["title"],
                r["location"],
                datetime.fromisoformat(r["starts_at"]),
                datetime.fromisoformat(r["ends_at"]),
                bool(r["all_day"]),
                bool(r["video"]),
                r["source"],
            )
            for r in rows
        ]

    def visible_to(self, viewer: Member) -> list[Member]:
        """Whose event details this person may see: their own, and anyone who shares with
        their partner."""
        return [
            m
            for m in self.store.list_members()
            if m.id == viewer.id or m.calendar_details == "partner"
        ]

    def context(self, viewer: Member) -> str:
        """Today's and tomorrow's events for the model, as data from outside ("" if none)."""
        tz = self._tz()
        today = clock.now().astimezone(tz).date()
        start = datetime(today.year, today.month, today.day, tzinfo=tz)
        end = start + timedelta(days=CONTEXT_DAYS)
        lines = [
            f"{owner.name} · {event_line(e, tz)}"
            for owner in self.visible_to(viewer)
            for e in self.entries(owner, start, end)
        ]
        return as_data("calendars", "\n".join(lines)) if lines else ""

    def _tz(self) -> ZoneInfo:
        family = self.store.get_family()
        return ZoneInfo(family.timezone if family else "UTC")


def _clock(moment: datetime) -> str:
    return moment.strftime("%I:%M %p").lstrip("0").replace(":00 ", " ").lower()


def event_line(entry: Entry, tz: ZoneInfo) -> str:
    begins = entry.starts_at.astimezone(tz)
    if entry.all_day:
        when = f"{begins:%a %d %b}, all day"
    else:
        ends = entry.ends_at.astimezone(tz)
        first = _clock(begins)
        if first[-2:] == _clock(ends)[-2:]:  # "10-11 am", not "10 am-11 am"
            first = first[:-3]
        when = f"{begins:%a %d %b}, {first}-{_clock(ends)}"
    text = f"{when}: {entry.title}"
    if entry.video:
        text += " (video call)"
    elif entry.location:
        text += f" (at {entry.location})"
    return text
