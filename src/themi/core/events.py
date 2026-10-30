"""Calendar events made and changed from chat, and suggested by booking emails (K3).

The family chose (2026-10-26), as groceries work (F5):
- asked for in their own words ("put the dentist on my calendar Tuesday at 3"): made at
  once, read back from what was stored;
- mentioned but not asked ("the plumber's coming Thursday morning"): a card;
- suggested by an email (triage finds the booking in a confirmation): a card, and after
  several approved in a row, Themi offers to make these automatic (their own rule: it covers
  only their calendar, F16a); made automatically, a message always says so;
- an event Themi made is changed or deleted at once; any other event only after a card
  (`calendar_event_change` is capped).

Dates and times come as fields (YYYY-MM-DD, HH:MM) and are checked here, not trusted: a
date that has passed, an end before the start or a time that isn't one is refused with an
example. Events go on the person's own calendar (their linked account's primary one) or on
the family "Themi" calendar for the wall (prompt 26's, under `calendar_write`).

Events Themi makes carry a private extended property ("event:<id>") and are recorded in
`themi_events`, so they're known before the next read of the calendar (K1) and show in
the context at once.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from themi import clock
from themi.accounts import LinkedAccount, Member
from themi.autonomy import ExecutionContext
from themi.channels.outbox import Priority
from themi.connectors.gcal import CalendarError, event_id
from themi.connectors.gcal.busy import TASK_BLOCK, Entry, event_line
from themi.connectors.google import CALENDAR_SCOPE
from themi.core.lists import name_key
from themi.core.rules import RuleError
from themi.core.tools import Proposal, ToolContext, ToolDeclined, ToolFailed, staged_tool
from themi.localtime import to_utc_iso

if TYPE_CHECKING:
    from themi.core.services import Services
    from themi.core.triage import Verdict

log = logging.getLogger(__name__)

OWN, CHANGE, FROM_EMAIL, FAMILY = (
    "calendar_event",
    "calendar_event_change",
    "calendar_from_email",
    "calendar_write",
)
ADD, MOVE, DELETE = "calendar.add_event", "calendar.move_event", "calendar.delete_event"
OFFER_AFTER = 3  # email events approved in a row before offering to make them automatic
EXAMPLE = "Try a date like 2026-11-03 and times like 15:00 (empty for an all-day event)."
MAX_TITLE = 120
INTENT = re.compile(r"\b(?:calendars?|schedule|book|booked)\b")
STOPWORDS = {"the", "a", "an", "my", "our", "to", "with", "for", "at", "on", "and", "of"}
# A meal with no time is at its usual one, not all day (bug #35); the card reads it back.
MEALS = {"breakfast": "08:00", "brunch": "10:30", "lunch": "12:00", "dinner": "18:00",
         "supper": "18:00"}  # fmt: skip
MEAL = re.compile(rf"\b({'|'.join(MEALS)})\b")
REPLACED_TEXT = "Replaced by the newer card."
MOVED_SINCE_TEXT = "Not needed now: that event has been changed since."
# "...plenty of time before tutoring": an event named as the time to fit around (bug #73).
ANCHOR = re.compile(r"\b(?:before|after|until|till|ahead of|around|than)\s+(?:the\s+|my\s+)?$")


@dataclass(frozen=True)
class When:
    starts: datetime
    ends: datetime
    all_day: bool


def parse_when(day: str, start: str, end: str, today: date, tz: ZoneInfo) -> When:
    """Checked fields: a date that hasn't passed, and times (or none, for all day)."""
    try:
        on = date.fromisoformat(day.strip())
    except ValueError as exc:
        raise ToolFailed(f"'{day}' isn't a date. {EXAMPLE}") from exc
    if on < today:
        raise ToolFailed(f"{on:%a %d %b} has already gone by. {EXAMPLE}")
    if not start.strip():
        begins = datetime(on.year, on.month, on.day, tzinfo=tz)
        return When(begins, begins + timedelta(days=1), True)
    begins = _at(on, _time(start), tz)
    ends = _at(on, _time(end), tz) if end.strip() else begins + timedelta(hours=1)
    if ends <= begins:
        raise ToolFailed(f"The end ({end}) comes before the start ({start}). {EXAMPLE}")
    return When(begins, ends, False)


def _at(day: date, at: time, tz: ZoneInfo) -> datetime:
    return datetime(day.year, day.month, day.day, at.hour, at.minute, tzinfo=tz)


def _time(text: str) -> time:
    m = re.fullmatch(r"\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\s*", text.lower())
    if not m:
        raise ToolFailed(f"'{text}' isn't a time. {EXAMPLE}")
    hour, minute = int(m.group(1)), int(m.group(2) or 0)
    if m.group(3):
        if not 1 <= hour <= 12:
            raise ToolFailed(f"'{text}' isn't a time. {EXAMPLE}")
        hour = hour % 12 + (12 if m.group(3) == "pm" else 0)
    if hour > 23 or minute > 59:
        raise ToolFailed(f"'{text}' isn't a time. {EXAMPLE}")
    return time(hour, minute)


FILLER = STOPWORDS | {"appointment", "appt", "event", "next", "this", "her", "his", "their"}


def _same_word(a: str, b: str) -> bool:
    """The same word, or one a form of the other ("tutoring" and "tutor", "pediatrics" and
    "pediatrician"): a shared start of five letters or more, most of the shorter word."""
    if a == b:
        return True
    shared = next(
        (i for i, (x, y) in enumerate(zip(a, b, strict=False)) if x != y), min(len(a), len(b))
    )
    return shared >= 5 and shared >= 0.6 * min(len(a), len(b))


def title_matches(words: str, title: str) -> bool:
    """Every word they used (bar fillers like "the" or "appointment") is in the title, give
    or take its ending (bug #20)."""
    wanted = [w for w in name_key(words).split() if w not in FILLER]
    have = name_key(title).split()
    return bool(wanted) and all(any(_same_word(w, h) for h in have) for w in wanted)


def words_in_common(said: str, title: str) -> int:
    """How many of the title's words (bar fillers and scraps like "s") they used, give or
    take endings ("contacted" and "contact")."""
    heard = name_key(said).split()
    words = {w for w in name_key(title).split() if len(w) > 2 and w not in FILLER}
    return sum(any(_same_word(w, h) for h in heard) for w in words)


def named_as_anchor(title: str, request_text: str) -> bool:
    """The title's words come up in what they said only as the time to fit around ("move
    that up so there's time before tutoring"): that event isn't the one to move (bug #73)."""
    said = name_key(request_text).split()
    words = [w for w in name_key(title).split() if w not in FILLER]
    hits = [i for i, w in enumerate(said) if any(_same_word(w, t) for t in words)]
    return bool(hits) and all(ANCHOR.search(" ".join(said[max(0, i - 3) : i]) + " ") for i in hits)


def asked_for(title: str, request_text: str) -> bool:
    """They asked for this event in their own words: the calendar (or booking) is
    mentioned, and so is every word of the title that matters."""
    said = name_key(request_text)
    if not INTENT.search(said):
        return False
    words = [w for w in name_key(title).split() if len(w) > 2 and w not in STOPWORDS]
    return bool(words) and all(re.search(rf"\b{re.escape(w)}", said) for w in words)


def when_words(when: When, tz: ZoneInfo) -> str:
    """ "Tue 03 Nov, 3-4 pm", or "Sat 24 Oct, all day"."""
    entry = Entry(0, "", "", when.starts, when.ends, when.all_day, False, None)
    return event_line(entry, tz).split(": ", 1)[0]


def describe(title: str, when: When, location: str, tz: ZoneInfo) -> str:
    """ "Dentist, Tue 03 Nov, 3-4 pm (at Smile Dental)": the read-back, from what's stored."""
    entry = Entry(0, title, location, when.starts, when.ends, when.all_day, False, None)
    on, rest = event_line(entry, tz).split(": ", 1)
    return f"{rest.split(' (at ')[0]}, {on}" + (f" (at {location})" if location else "")


@dataclass(frozen=True)
class Found:
    """An event of theirs that a tool named."""

    account_id: int
    calendar_id: str
    event_id: str
    title: str
    location: str
    when: When
    themi_id: int | None  # in themi_events: Themi made it


class Events:
    def __init__(self, services: Services) -> None:
        self.services = services
        self.db = services.store.db

    def install(self) -> None:
        s = self.services
        s.events = self
        for name, executor in ((ADD, self._execute_add), (MOVE, self._execute_move)):
            s.autonomy.executors.register(name)(executor)
        s.autonomy.executors.register(DELETE)(self._execute_delete)
        for t in (add_calendar_event, move_calendar_event, delete_calendar_event):
            s.tools.register(t)
        if s.triage is not None:
            s.triage.verdict_listeners.append(self.on_email)

    # ----- where events go ----------------------------------------------------------------

    def own_account(self, member: Member) -> LinkedAccount:
        for account in self.services.store.linked_accounts(member.id):
            if account.enabled and account.allows(CALENDAR_SCOPE):
                return account
        raise ToolFailed(
            "They haven't linked a Google account with calendar access (My accounts on the "
            "website)."
        )

    async def _target(self, member: Member, calendar: str) -> tuple[int, str]:
        if calendar == "family":
            sync = self.services.calendar
            if sync is None:
                raise ToolFailed("The family calendar isn't set up.")
            target = await sync.target()
            return target.account.id, target.calendar_id
        return self.own_account(member).id, "primary"

    # ----- finding their events -----------------------------------------------------------

    def find(self, member: Member, words: str, on: str) -> Found:
        """The one event of theirs they mean, by its title's words (and day, if given)."""
        tz = self._tz()
        day = date.fromisoformat(on) if on.strip() else None
        start = _at(day or self._today(), time(0), tz)
        end = start + (timedelta(days=1) if day else timedelta(days=60))
        found: dict[str, Found] = {}
        for row in self.db.query(
            "SELECT * FROM themi_events WHERE member_id = ? AND deleted_at IS NULL "
            "AND ends_at > ? AND starts_at < ?",
            (member.id, to_utc_iso(start), to_utc_iso(end)),
        ):
            found[row["event_id"]] = self._found(row, row["id"])
        for row in self.db.query(
            "SELECT * FROM calendar_entries WHERE member_id = ? AND ends_at > ? AND starts_at < ?",
            (member.id, to_utc_iso(start), to_utc_iso(end)),
        ):
            if row["event_id"] not in found:
                found[row["event_id"]] = self._found(row, None)
        matches = [f for f in found.values() if title_matches(words, f.title)]
        if len(matches) == 1:
            return matches[0]
        listed = "; ".join(f"{f.title} ({when_words(f.when, tz)})" for f in matches[:6])
        if matches:
            raise ToolFailed(
                f'More than one event matches "{words}": {listed}. Ask which, or give its date.'
            )
        raise ToolFailed(
            f'No event of theirs matches "{words}"{f" on {day:%a %d %b}" if day else ""}.'
        )

    @staticmethod
    def _found(row: dict[str, Any], themi_id: int | None) -> Found:
        when = When(
            datetime.fromisoformat(row["starts_at"]),
            datetime.fromisoformat(row["ends_at"]),
            bool(row["all_day"]),
        )
        return Found(
            row["account_id"], row["calendar_id"], row["event_id"], row["title"],
            row["location"], when, themi_id,
        )  # fmt: skip

    def made_that_day(self, member: Member, calendar: str, title: str, when: When) -> Found | None:
        """An event Themi made on that calendar with this title on the same day (bug #35:
        the lunch went on three times)."""
        tz = self._tz()
        start = _at(when.starts.astimezone(tz).date(), time(0), tz)
        whose = (
            "calendar_id != 'primary'"
            if calendar == "family"
            else ("calendar_id = 'primary' AND member_id = ?")
        )
        for row in self.db.query(
            f"SELECT * FROM themi_events WHERE {whose} AND deleted_at IS NULL "
            "AND source NOT LIKE ? AND starts_at >= ? AND starts_at < ?",
            (
                *(() if calendar == "family" else (member.id,)),
                f"{TASK_BLOCK}%", to_utc_iso(start), to_utc_iso(start + timedelta(days=1)),
            ),
        ):  # fmt: skip
            if name_key(row["title"]) == name_key(title):
                return self._found(row, row["id"])
        return None

    async def replace_waiting(self, member: Member, payload: dict[str, Any]) -> None:
        """A card still waiting for the same event (title, day and calendar) gives way to the
        new one; the very same event is already waiting, so nothing new (bug #35)."""
        tz = self._tz()
        day = datetime.fromisoformat(payload["starts"]).astimezone(tz).date()
        for row in self.db.query(
            "SELECT id, payload FROM pending_actions WHERE member_id = ? AND executor = ? "
            "AND status IN ('pending', 'snoozed') ORDER BY id",
            (member.id, ADD),
        ):
            old = json.loads(row["payload"])
            if (
                old.get("calendar") != payload["calendar"]
                or name_key(str(old.get("title", ""))) != name_key(payload["title"])
                or datetime.fromisoformat(old["starts"]).astimezone(tz).date() != day
            ):
                continue
            if (old["starts"], old["ends"]) == (payload["starts"], payload["ends"]):
                raise ToolDeclined("That's already waiting for a yes on its card.")
            await self.services.autonomy.withdraw(row["id"], REPLACED_TEXT)

    async def withdraw_changes(self, event_id: str, keep: int | None = None) -> None:
        """Cards still waiting to move or delete this event give way: a newer change was
        asked for or made (bug #81: a declined move came back after another was approved)."""
        for row in self.db.query(
            "SELECT id, executor, payload FROM pending_actions WHERE executor IN (?, ?) "
            "AND status IN ('pending', 'snoozed') ORDER BY id",
            (MOVE, DELETE),
        ):
            if row["id"] != keep and json.loads(row["payload"]).get("event_id") == event_id:
                await self.services.autonomy.withdraw(row["id"], MOVED_SINCE_TEXT)

    # ----- doing it -----------------------------------------------------------------------

    async def _execute_add(self, payload: dict[str, Any], ctx: ExecutionContext) -> str:
        _, text = await self.make(ctx.member, payload, ctx.idempotency_key)
        if str(payload["source"]).startswith("email:"):
            await self._after_email_event(ctx, text)
        return text

    async def make(self, member: Member, payload: dict[str, Any], key: str) -> tuple[int, str]:
        """Put an event on the calendar from an add payload; returns its `themi_events` id
        and the read-back. `key` (the action's) keeps a retry from making it twice."""
        tz = self._tz()
        when = When(
            datetime.fromisoformat(payload["starts"]),
            datetime.fromisoformat(payload["ends"]),
            bool(payload["all_day"]),
        )
        title, location = str(payload["title"]), str(payload.get("location") or "")
        account_id, calendar_id = await self._target(member, str(payload["calendar"]))
        made = self.db.one("SELECT * FROM themi_events WHERE action_key = ?", (key,))
        if made is None:  # idempotent: a retry doesn't make it twice
            themi_id = self.db.execute(
                "INSERT INTO themi_events (member_id, account_id, calendar_id, event_id, title, "
                "location, starts_at, ends_at, all_day, source, action_key, created_at) "
                "VALUES (?, ?, ?, '', ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    member.id, account_id, calendar_id, title, location,
                    to_utc_iso(when.starts), to_utc_iso(when.ends), int(when.all_day),
                    payload["source"], key, to_utc_iso(clock.now()),
                ),
            )  # fmt: skip
            eid = event_id("event", themi_id, self._seed())
            self.db.execute("UPDATE themi_events SET event_id = ? WHERE id = ?", (eid, themi_id))
        else:
            themi_id, eid = made["id"], made["event_id"]
        await self._write(account_id, calendar_id, eid, title, location, when, themi_id)
        if payload["calendar"] != "family":
            self._show(member, account_id, calendar_id, eid, title, location, when, themi_id)
        where = "the family calendar" if payload["calendar"] == "family" else "your calendar"
        return themi_id, f"On {where}: {describe(title, when, location, tz)}."

    async def _execute_move(self, payload: dict[str, Any], ctx: ExecutionContext) -> str:
        found = self._payload_found(payload)
        when = When(
            datetime.fromisoformat(payload["starts"]),
            datetime.fromisoformat(payload["ends"]),
            bool(payload["all_day"]),
        )
        if found.themi_id is not None:
            await self._write(found.account_id, found.calendar_id, found.event_id, found.title,
                              found.location, when, found.themi_id)  # fmt: skip
            self.db.execute(
                "UPDATE themi_events SET starts_at = ?, ends_at = ?, all_day = ? WHERE id = ?",
                (to_utc_iso(when.starts), to_utc_iso(when.ends), int(when.all_day), found.themi_id),
            )
        else:  # someone else's event: everything else on it stays as it is
            client = self._client(found.account_id)
            event = await client.get_event(found.calendar_id, found.event_id)
            event.update(_times(when, self._tz()))
            await client.update_event(found.calendar_id, found.event_id, event)
        self.db.execute(
            "UPDATE calendar_entries SET starts_at = ?, ends_at = ?, all_day = ? "
            "WHERE event_id = ?",
            (to_utc_iso(when.starts), to_utc_iso(when.ends), int(when.all_day), found.event_id),
        )
        await self.withdraw_changes(found.event_id, keep=ctx.action_id)
        return f"Moved: {describe(found.title, when, found.location, self._tz())}."

    async def _execute_delete(self, payload: dict[str, Any], ctx: ExecutionContext) -> str:
        found = self._payload_found(payload)
        await self._client(found.account_id).delete_event(found.calendar_id, found.event_id)
        if found.themi_id is not None:
            self.db.execute(
                "UPDATE themi_events SET deleted_at = ? WHERE id = ?",
                (to_utc_iso(clock.now()), found.themi_id),
            )
        self.db.execute("DELETE FROM calendar_entries WHERE event_id = ?", (found.event_id,))
        await self.withdraw_changes(found.event_id, keep=ctx.action_id)
        return f"Deleted from the calendar: {describe(found.title, found.when, '', self._tz())}."

    async def _write(
        self, account_id: int, calendar_id: str, eid: str, title: str, location: str,
        when: When, themi_id: int,
    ) -> None:  # fmt: skip
        sync = self.services.calendar
        if sync is None:
            raise CalendarError("Google isn't set up")
        body = {
            "summary": title,
            "location": location,
            **_times(when, self._tz()),
            "extendedProperties": {"private": {"themi": self._marker(themi_id)}},
        }
        await sync.upsert(account_id, calendar_id, eid, body)

    def _marker(self, themi_id: int) -> str:
        """What the event carries: "task-block:<task>" for time blocked for a task (K5: never
        busy time), else "event:<id>"."""
        source = self.db.scalar("SELECT source FROM themi_events WHERE id = ?", (themi_id,))
        return source if str(source or "").startswith(TASK_BLOCK) else f"event:{themi_id}"

    def _show(
        self, member: Member, account_id: int, calendar_id: str, eid: str, title: str,
        location: str, when: When, themi_id: int,
    ) -> None:  # fmt: skip
        """Into the calendar read (K1) now, rather than at the next refresh."""
        self.db.execute("DELETE FROM calendar_entries WHERE event_id = ?", (eid,))
        self.db.execute(
            "INSERT INTO calendar_entries (member_id, account_id, calendar_id, event_id, title, "
            "location, starts_at, ends_at, all_day, video, busy, source, fetched_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)",
            (
                member.id, account_id, calendar_id, eid, title, location,
                to_utc_iso(when.starts), to_utc_iso(when.ends), int(when.all_day),
                int(not when.all_day and not self._marker(themi_id).startswith(TASK_BLOCK)),
                self._marker(themi_id), to_utc_iso(clock.now()),
            ),
        )  # fmt: skip

    def _payload_found(self, payload: dict[str, Any]) -> Found:
        when = When(
            datetime.fromisoformat(payload["was_starts"]),
            datetime.fromisoformat(payload["was_ends"]),
            bool(payload["was_all_day"]),
        )
        return Found(
            int(payload["account_id"]), str(payload["calendar_id"]), str(payload["event_id"]),
            str(payload["title"]), str(payload.get("location") or ""), when,
            payload.get("themi_id"),
        )  # fmt: skip

    # ----- from email ---------------------------------------------------------------------

    async def on_email(
        self, member: Member, account: LinkedAccount, row: dict[str, Any], verdict: Verdict
    ) -> None:
        """Triage's verdict listener: a booking in a new confirmation becomes a card."""
        event = verdict.event
        if event is None or row["initial"]:
            return
        source = f"email:{row['id']}"
        if self.db.one(
            "SELECT 1 FROM pending_actions WHERE category = ? AND payload LIKE ?",
            (FROM_EMAIL, f'%"source": "{source}"%'),
        ):
            return
        try:
            when = parse_when(
                event["date"], event["start"], event["end"], self._today(), self._tz()
            )
        except ToolFailed:
            log.info("Email %s's booking had no usable date or time", row["id"])
            return
        title = event["title"][:MAX_TITLE]
        await self.services.autonomy.stage(
            FROM_EMAIL,
            member,
            f"From an email: {describe(title, when, event['location'], self._tz())}, for your "
            "calendar",
            _add_payload(title, event["location"], when, "mine", source),
            ADD,
            expires=when.ends,  # a card about a delivery that's been and gone: no use (F15b)
        )

    async def _after_email_event(self, ctx: ExecutionContext, text: str) -> None:
        automatic = self.db.scalar(
            "SELECT automatic FROM pending_actions WHERE id = ?", (ctx.action_id,)
        )
        if automatic:  # made without asking: always said
            await self.services.outbox.send(
                ctx.member,
                f"Added to your calendar from an email: {text.split(': ', 1)[1]}",
                priority=Priority.NORMAL,
                kind="calendar",
            )
            return
        await self._maybe_offer(ctx.member, ctx.action_id)

    async def _maybe_offer(self, member: Member, current: int) -> None:
        """After several email events approved in a row (this one, being made now, and the
        ones before it), offer to make them automatic."""
        rulebook = self.services.rulebook
        if rulebook is None or self.db.one(
            "SELECT 1 FROM rules WHERE category = ? AND affects = ?", (FROM_EMAIL, member.id)
        ):
            return  # offered to them before (whatever came of it), or no rules here
        statuses = [
            r["status"]
            for r in self.db.query(
                "SELECT status FROM pending_actions WHERE category = ? AND member_id = ? "
                "AND id != ? AND automatic = 0 AND status IN ('done', 'declined') "
                "ORDER BY id DESC LIMIT ?",
                (FROM_EMAIL, member.id, current, OFFER_AFTER - 1),
            )
        ]
        if statuses != ["done"] * (OFFER_AFTER - 1):
            return
        try:
            await rulebook.propose(
                member,
                "Add events from my booking emails to my calendar without asking",
                "When a booking confirmation email describes an upcoming event, Themi puts it "
                f"on {member.name}'s calendar without asking first, and always sends a message "
                "saying it did.",
                "autonomy_grant",
                FROM_EMAIL,
            )  # as a reply: it comes straight after their yes
        except RuleError as exc:  # no offer
            log.info("No offer to make email events automatic: %s", exc)

    # ----- small things -------------------------------------------------------------------

    def _client(self, account_id: int) -> Any:
        sync = self.services.calendar
        if sync is None:
            raise CalendarError("Google isn't set up")
        return sync.client(account_id)

    def _seed(self) -> str:
        family = self.services.store.get_family()
        return family.created_at.isoformat() if family else "themi"

    def _today(self) -> date:
        return clock.now().astimezone(self._tz()).date()

    def _tz(self) -> ZoneInfo:
        family = self.services.store.get_family()
        return ZoneInfo(family.timezone if family else "UTC")


def _times(when: When, tz: ZoneInfo) -> dict[str, Any]:
    if when.all_day:
        return {
            "start": {"date": when.starts.astimezone(tz).date().isoformat()},
            "end": {"date": when.ends.astimezone(tz).date().isoformat()},
        }
    return {
        "start": {"dateTime": when.starts.isoformat(), "timeZone": str(tz)},
        "end": {"dateTime": when.ends.isoformat(), "timeZone": str(tz)},
    }


def _add_payload(
    title: str, location: str, when: When, calendar: str, source: str
) -> dict[str, Any]:
    return {
        "title": title,
        "location": location,
        "starts": when.starts.isoformat(),
        "ends": when.ends.isoformat(),
        "all_day": when.all_day,
        "calendar": calendar,
        "source": source,
    }


def _found_payload(found: Found) -> dict[str, Any]:
    return {
        "account_id": found.account_id,
        "calendar_id": found.calendar_id,
        "event_id": found.event_id,
        "title": found.title,
        "location": found.location,
        "was_starts": found.when.starts.isoformat(),
        "was_ends": found.when.ends.isoformat(),
        "was_all_day": found.when.all_day,
        "themi_id": found.themi_id,
    }


def _events(ctx: ToolContext) -> Events:
    events = ctx.services.events
    if events is None:
        raise ToolFailed("Calendars aren't set up.")
    return events


@staged_tool(
    "add_calendar_event",
    "Put an event on someone's calendar: their own ('mine') or the family calendar on the "
    "wall ('family'). date: YYYY-MM-DD from the local date in the context; start and end: "
    "HH:MM, 24-hour (end empty for an hour; both empty for all day; a meal with no time "
    "gets its usual one). location: as they said it, or ''. Asked for in their own words, "
    "it's made at once; otherwise they get a card. A correction to a card still waiting "
    "replaces it; to change an event already made, use move_calendar_event.",
    {
        "title": {"type": "string"},
        "date": {"type": "string"},
        "start": {"type": "string"},
        "end": {"type": "string"},
        "location": {"type": "string"},
        "calendar": {"type": "string", "enum": ["mine", "family"]},
    },
)
async def add_calendar_event(ctx: ToolContext, args: dict[str, Any]) -> Proposal:
    events = _events(ctx)
    title = " ".join(str(args["title"]).split())[:MAX_TITLE]
    if not title:
        raise ToolFailed("An event needs a title.")
    if args["calendar"] == "mine":
        events.own_account(ctx.member)  # fails early, with what to do, if there's none
    start, end = str(args["start"]), str(args["end"])
    meal = MEAL.search(name_key(title))
    if meal and not start.strip():
        start, end = MEALS[meal.group(1)], ""
    when = parse_when(args["date"], start, end, events._today(), events._tz())
    location = " ".join(str(args["location"]).split())[:200]
    calendar = str(args["calendar"])
    where = "the family calendar" if calendar == "family" else "your calendar"
    tz = events._tz()
    same = events.made_that_day(ctx.member, calendar, title, when)
    if same is not None and same.when == when:
        raise ToolDeclined(
            f"Already on {where}: {describe(same.title, same.when, same.location, tz)}. "
            "Nothing new was added."
        )
    if same is not None:
        raise ToolFailed(
            f"{same.title} is already on {where} ({when_words(same.when, tz)}). To change "
            "its time, use move_calendar_event."
        )
    payload = _add_payload(title, location, when, calendar, "chat")
    await events.replace_waiting(ctx.member, payload)
    proposal = Proposal(
        FAMILY if calendar == "family" else OWN,
        f"{describe(title, when, location, tz)}, for {where}",
        ADD,
        payload,
    )
    # Over by then, it's no use (bug #90's thread: Tuesday's card still waited on Thursday).
    return replace(proposal, requested=asked_for(title, ctx.request_text), expires=when.ends)


@staged_tool(
    "move_calendar_event",
    "Move one of their calendar events to a new date or time. event: words from the title of "
    "the event to move, never one named as the time to fit around ('before tutoring'); a "
    "task (a run, a chore) is reschedule_task, even with a time of day. on: its current date "
    "(YYYY-MM-DD) if there could be more than one, else ''. date, start, end as for "
    "add_calendar_event. Events Themi made move at once; others need their yes.",
    {
        "event": {"type": "string"},
        "on": {"type": "string"},
        "date": {"type": "string"},
        "start": {"type": "string"},
        "end": {"type": "string"},
    },
)
async def move_calendar_event(ctx: ToolContext, args: dict[str, Any]) -> Proposal:
    events = _events(ctx)
    found = events.find(ctx.member, args["event"], args["on"])
    if named_as_anchor(found.title, ctx.request_text):
        raise ToolFailed(
            f"They named {found.title} as the time to fit around, not as the one to move. "
            "If they meant a task (a run, a chore), reschedule_task changes its time; "
            "otherwise ask which one."
        )
    when = parse_when(args["date"], args["start"], args["end"], events._today(), events._tz())
    await events.withdraw_changes(found.event_id)
    payload = {
        **_found_payload(found),
        "starts": when.starts.isoformat(),
        "ends": when.ends.isoformat(),
        "all_day": when.all_day,
    }
    summary = f"Moving {found.title} to {when_words(when, events._tz())}"
    proposal = Proposal(OWN if found.themi_id else CHANGE, summary, MOVE, payload)
    # No use once the time it moves to has come (bug #90: it came back at 1:33 for 12).
    return replace(proposal, requested=found.themi_id is not None, expires=when.starts)


@staged_tool(
    "delete_calendar_event",
    "Take one of their events off the calendar. event: words from its title; on: its date "
    "(YYYY-MM-DD) if there could be more than one, else ''. Events Themi made go at once; "
    "others need their yes.",
    {"event": {"type": "string"}, "on": {"type": "string"}},
)
async def delete_calendar_event(ctx: ToolContext, args: dict[str, Any]) -> Proposal:
    events = _events(ctx)
    found = events.find(ctx.member, args["event"], args["on"])
    await events.withdraw_changes(found.event_id)
    proposal = Proposal(
        OWN if found.themi_id else CHANGE,
        f"Deleting {found.title} ({when_words(found.when, events._tz())}) from the calendar",
        DELETE,
        _found_payload(found),
    )
    return replace(proposal, requested=found.themi_id is not None)
