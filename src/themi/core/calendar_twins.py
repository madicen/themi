"""The same event twice (F34e, Erin's idea #175).

After each calendar read, one person's events are looked over for pairs that are the same
thing: on the same day, overlapping, with titles that match ("Dentist" and "Dentist
cleaning"), or both appointment-like (her placeholder "ND psych in person" over the clinic's
"Return Patient Visit with ... MD"), or the same title and times on two calendars. Meetings
with other guests, events of a series, Themi's time blocks and copies, and a copy Themi made
of the other one (someone asked for it) are left alone.

- The same title, times and place on one calendar: merged on its own (`calendar_twins`, Tier
  2 unless the family changed it), and said once in one line.
- Otherwise one card per pair: on one calendar [Merge them] [Not the same]; on two [Keep on
  mine] [Keep on family] [Keep on both] [Your call] [Not the same]. The tap is the yes.
- Their setting "The same event on two of my calendars": ask (the card), guess (merged where
  the fuller one is, said in one line with [Undo] for a day), or keep (left as they are).

Every pair is seen once (`calendar_twins`, by its two event ids), so nothing is asked twice.
Cards go through the outbox like every message (quiet hours, the daily limit).
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta
from itertools import combinations
from typing import TYPE_CHECKING, Any

from themi import clock
from themi.accounts import Member
from themi.autonomy import ExecutionContext
from themi.channels.events import Button, InboundEvent
from themi.channels.outbox import Priority
from themi.connectors.gcal.busy import TASK_BLOCK
from themi.core import keys
from themi.core.calendar_view import CalendarPreferences
from themi.core.events import MERGE, Events, Found, When, title_matches
from themi.core.lists import name_key
from themi.localtime import to_utc_iso

if TYPE_CHECKING:
    from themi.core.services import Services

log = logging.getLogger(__name__)

CATEGORY = "calendar_twins"
UNMERGE = "calendar.unmerge_events"
KIND = "calendar_twin"
LOOK_AHEAD = timedelta(days=14)
UNDO_FOR = timedelta(days=1)
COPY = "copy:"  # F34f: a copy Themi keeps of an event on another calendar

# Words that make a title an appointment: two of these at the same time are one visit.
APPOINTMENT = re.compile(
    r"\b(?:appt|appointment|visit|doctor|dr|md|nd|psych\w*|therap\w*|dentist|dental|"
    r"clinic|check-?up|patient|ortho\w*|physio\w*|derm\w*|pediatric\w*|optometr\w*|eye exam|"
    r"vet|counsel\w*|consult\w*|follow-?up|telehealth)\b",
    re.IGNORECASE,
)

ASK_TEXT = "These look like the same thing, on {day}:\n{lines}\n{question}"
ONE_CALENDAR_ASK = "Merge them into one?"
TWO_CALENDARS_ASK = "One event, on which calendar?"
TOLD_TEXT = "{title} was on your calendar twice on {day}, so it's one event now."
GUESSED_TEXT = "{summary}. Undo is here for a day."
APART_TEXT = "Leaving them as they are."
GONE_TEXT = "Not needed now: one of them has changed or gone since."
UNDO_LATE_TEXT = "It's been more than a day, so that can't be undone from here now."
UNDONE_TEXT = "Put back as they were: {first} and {second}."
CHOICES = {"mine": "Keep on mine", "family": "Keep on family", "both": "Keep on both",
           "auto": "Your call"}  # fmt: skip


def appointment_like(title: str) -> bool:
    return bool(APPOINTMENT.search(title))


def alike(a: Found, b: Found) -> bool:
    """Two events that could be one thing, by their titles."""
    if name_key(a.title) == name_key(b.title):
        return True
    if title_matches(a.title, b.title) or title_matches(b.title, a.title):
        return True
    return appointment_like(a.title) and appointment_like(b.title)


def overlap(a: When, b: When) -> bool:
    if a.all_day or b.all_day:
        return a.all_day and b.all_day and a.starts == b.starts
    return a.starts < b.ends and b.starts < a.ends


class CalendarTwins:
    def __init__(self, services: Services, events: Events) -> None:
        self.services = services
        self.events = events
        self.db = services.store.db

    def install(self) -> None:
        s = self.services
        s.autonomy.executors.register(UNMERGE)(self._execute_unmerge)
        s.button_handlers[KIND] = self.on_button
        if s.maybe(keys.calendars) is not None:
            s.get(keys.calendars).listeners.append(self.check)

    # ----- finding pairs ------------------------------------------------------------------

    def pairs(self, member: Member) -> list[tuple[Found, Found]]:
        """Their events in the next two weeks that look like one thing twice, not seen yet."""
        now = clock.now()
        rows = self.db.query(
            "SELECT * FROM calendar_entries WHERE member_id = ? AND ends_at > ? AND starts_at < ? "
            "AND guests = 0 AND recurring = 0 ORDER BY starts_at, event_id",
            (member.id, to_utc_iso(now), to_utc_iso(now + LOOK_AHEAD)),
        )
        made = {
            r["event_id"]
            for r in self.db.query(
                "SELECT event_id FROM themi_events WHERE member_id = ? AND deleted_at IS NULL",
                (member.id,),
            )
        }
        found = [
            Events._found(r, None)
            for r in rows
            if not str(r["source"] or "").startswith((TASK_BLOCK, COPY))
        ]
        found = list({f.event_id: f for f in found}.values())  # one row per event
        out = []
        for a, b in combinations(found, 2):
            if not overlap(a.when, b.when) or not alike(a, b):
                continue
            if self._seen(member, a, b):
                continue
            same = name_key(a.title) == name_key(b.title) and a.when == b.when
            if same and (a.event_id in made or b.event_id in made):
                continue  # a copy Themi made when someone asked (F29a): meant to be there
            out.append((a, b))
        return out

    def _key(self, a: Found, b: Found) -> tuple[str, str]:
        first, second = sorted((a.event_id, b.event_id))
        return first, second

    def _seen(self, member: Member, a: Found, b: Found) -> bool:
        return bool(
            self.db.one(
                "SELECT 1 FROM calendar_twins WHERE member_id = ? AND first_id = ? "
                "AND second_id = ?",
                (member.id, *self._key(a, b)),
            )
        )

    def _record(self, member: Member, a: Found, b: Found, answer: str) -> int:
        return self.db.execute(
            "INSERT INTO calendar_twins (member_id, first_id, second_id, answer, seen_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (member.id, *self._key(a, b), answer, to_utc_iso(clock.now())),
        )

    # ----- after each read ----------------------------------------------------------------

    async def check(self, member: Member) -> int:
        """The calendar read's listener: each new pair merged, offered or left. Returns how
        many pairs were found."""
        member = self.services.store.get_member(member.id)
        pairs = self.pairs(member)
        for a, b in pairs:
            try:
                await self._one(member, a, b)
            except Exception:
                log.exception("Couldn't settle a pair of events for member %s", member.id)
        return len(pairs)

    async def _one(self, member: Member, a: Found, b: Found) -> None:
        identical = (
            a.account_id == b.account_id
            and a.calendar_id == b.calendar_id
            and name_key(a.title) == name_key(b.title)
            and a.when == b.when
            and name_key(a.location) == name_key(b.location)
        )
        apart = (a.account_id, a.calendar_id) != (b.account_id, b.calendar_id)
        if identical:
            twin = self._record(member, a, b, "merged")
            outcome = await self._merge(member, twin, a, b, "")
            if outcome.action.status == "done":
                day = f"{a.when.starts.astimezone(self.events._tz()):%a %d %b}"
                await self.services.outbox.send(
                    member, TOLD_TEXT.format(title=a.title, day=day), priority=Priority.NORMAL,
                    kind=KIND,
                )  # fmt: skip
            return
        if (
            apart
            and self.services.store.preferences(member.id, CalendarPreferences).calendar_twins
            == "keep"
        ):
            self._record(member, a, b, "kept")
            return
        if (
            apart
            and self.services.store.preferences(member.id, CalendarPreferences).calendar_twins
            == "guess"
        ):
            await self._guess(member, a, b)
            return
        await self._ask(member, a, b, apart)

    async def _ask(self, member: Member, a: Found, b: Found, apart: bool) -> None:
        twin = self._record(member, a, b, "asked")
        tz = self.events._tz()
        day = f"{a.when.starts.astimezone(tz):%a %d %b}"
        lines = "\n".join(
            f"- {f.title}, {_times(f.when, tz)} ({self.events.calendar_words(f, to_them=True)})"
            for f in (a, b)
        )
        question = TWO_CALENDARS_ASK if apart else ONE_CALENDAR_ASK

        def button(label: str, keep_on: str) -> Button:
            return Button(label, KIND, {"twin": twin, "keep_on": keep_on})

        buttons = (
            [button(label, key) for key, label in CHOICES.items()]
            if apart
            else [button("Merge them", "auto")]
        )
        buttons.append(button("Not the same", "apart"))
        await self.services.outbox.send(
            member, ASK_TEXT.format(day=day, lines=lines, question=question),
            priority=Priority.NORMAL, kind=KIND, buttons=buttons,
        )  # fmt: skip

    async def _guess(self, member: Member, a: Found, b: Found) -> None:
        twin = self._record(member, a, b, "guessed")
        undo = {"a": _found_json(a), "b": _found_json(b)}
        self.db.execute("UPDATE calendar_twins SET undo = ? WHERE id = ?", (json.dumps(undo), twin))
        outcome = await self._merge(member, twin, a, b, "auto")
        if outcome.action.status != "done":
            return  # a card went out instead (the category was set to ask)
        _, summary = self.events.merge_payload(a, b, "auto")
        said = summary.replace("Merging ", "Merged ", 1).replace(": one event on ", ", on ", 1)
        await self.services.outbox.send(
            member, GUESSED_TEXT.format(summary=said), priority=Priority.NORMAL, kind=KIND,
            buttons=[Button("Undo", KIND, {"twin": twin, "keep_on": "undo"})],
        )  # fmt: skip

    async def _merge(self, member: Member, twin: int, a: Found, b: Found, keep_on: str) -> Any:
        payload, summary = self.events.merge_payload(a, b, keep_on)
        outcome = await self.services.autonomy.stage(
            CATEGORY, member, summary, payload, MERGE, requested=True, expires=a.when.ends,
        )  # fmt: skip
        self.db.execute(
            "UPDATE calendar_twins SET action_id = ?, answered_at = ? WHERE id = ?",
            (outcome.action.id, to_utc_iso(clock.now()), twin),
        )
        return outcome

    # ----- taps ---------------------------------------------------------------------------

    async def on_button(self, event: InboundEvent) -> None:
        assert event.button is not None
        payload = event.button.payload
        member = event.member
        row = self.db.one(
            "SELECT * FROM calendar_twins WHERE id = ? AND member_id = ?",
            (int(payload.get("twin", 0)), member.id),
        )
        if row is None:
            return
        keep_on = str(payload.get("keep_on") or "")
        if keep_on == "undo":
            text = await self._undo(member, row)
        elif row["answer"] != "asked":
            text = "That one's settled already."
        elif keep_on == "apart":
            self._answer(row["id"], "apart")
            text = APART_TEXT
        else:
            text = await self._chosen(member, row, keep_on)
        if event.button.message_id is not None:
            await self.services.outbox.edit(member, event.button.message_id, text, ())

    def _answer(self, twin: int, answer: str) -> None:
        self.db.execute(
            "UPDATE calendar_twins SET answer = ?, answered_at = ? WHERE id = ?",
            (answer, to_utc_iso(clock.now()), twin),
        )

    def _now_found(self, member: Member, event_id: str) -> Found | None:
        row = self.db.one(
            "SELECT * FROM calendar_entries WHERE member_id = ? AND event_id = ?",
            (member.id, event_id),
        )
        return Events._found(row, None) if row is not None else None

    async def _chosen(self, member: Member, row: dict[str, Any], keep_on: str) -> str:
        a, b = self._now_found(member, row["first_id"]), self._now_found(member, row["second_id"])
        if a is None or b is None:
            self._answer(row["id"], "gone")
            return GONE_TEXT
        self._answer(row["id"], keep_on)
        outcome = await self._merge(member, row["id"], a, b, keep_on)
        return str(outcome.message)

    async def _undo(self, member: Member, row: dict[str, Any]) -> str:
        if not row["undo"] or not row["action_id"]:
            return "There's nothing to undo there."
        answered = datetime.fromisoformat(row["answered_at"] or row["seen_at"])
        if clock.now() > answered + UNDO_FOR:
            return UNDO_LATE_TEXT
        if row["answer"] == "undone":
            return "That's been put back already."
        undo = json.loads(row["undo"])
        merged = self.db.one(
            "SELECT payload FROM pending_actions WHERE id = ?", (row["action_id"],)
        )
        payload = {**undo, "merge": json.loads(merged["payload"]) if merged else {}}
        first, second = _from_json(undo["a"]), _from_json(undo["b"])
        outcome = await self.services.autonomy.stage(
            CATEGORY, member, f"Putting back {first.title} and {second.title}", payload, UNMERGE,
            requested=True,
        )  # fmt: skip
        if outcome.action.status == "done":
            self._answer(row["id"], "undone")
        return str(outcome.message)

    async def _execute_unmerge(self, payload: dict[str, Any], ctx: ExecutionContext) -> str:
        """A best-guess merge put back: the kept event gets its own title, place and times
        again (the notes stay merged: they were never kept apart), and the other is back."""
        merge = payload.get("merge") or {}
        keep_id = str((merge.get("keep") or {}).get("event_id") or "")
        originals = [_from_json(payload["a"]), _from_json(payload["b"])]
        for found in originals:
            if found.event_id == keep_id:
                await self.events._change(found, found.when, found.title, found.location, {})
                continue
            sync = self.services.maybe(keys.calendar)
            if sync is None:
                raise RuntimeError("Google isn't set up")
            body = {
                "summary": found.title,
                "location": found.location,
                **_google_times(found.when, self.events._tz()),
            }
            await sync.upsert(found.account_id, found.calendar_id, found.event_id, body)
        if (
            self.services.maybe(keys.calendars) is not None
        ):  # the pair's row keeps it from being asked
            await self.services.get(keys.calendars).refresh(ctx.member)
        return UNDONE_TEXT.format(first=originals[0].title, second=originals[1].title)


def _times(when: When, tz: Any) -> str:
    from themi.core.events import when_words

    return when_words(when, tz).split(", ", 1)[-1]


def _google_times(when: When, tz: Any) -> dict[str, Any]:
    from themi.core.events import _times as event_times

    return event_times(when, tz)


def _found_json(found: Found) -> dict[str, Any]:
    return {
        "account_id": found.account_id,
        "calendar_id": found.calendar_id,
        "event_id": found.event_id,
        "title": found.title,
        "location": found.location,
        "starts": found.when.starts.isoformat(),
        "ends": found.when.ends.isoformat(),
        "all_day": found.when.all_day,
    }


def _from_json(data: dict[str, Any]) -> Found:
    when = When(
        datetime.fromisoformat(data["starts"]),
        datetime.fromisoformat(data["ends"]),
        bool(data["all_day"]),
    )
    return Found(
        int(data["account_id"]), str(data["calendar_id"]), str(data["event_id"]),
        str(data["title"]), str(data["location"]), when, None,
    )  # fmt: skip
