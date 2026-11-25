"""Travel time and "time to get ready" (K4).

For an event with a place (not a video call, not all day, not at home), a heads-up comes
when it's time to start getting ready: "Dentist at 3, about 35 min with traffic: leave
around 2:20." It's worked out from:

- home: the family's address, found on the map once (`family_home`, the Family page);
- the event's place, found on the map once and remembered (`geocodes`);
- the drive: TomTom with live traffic, arriving at the start, when there's a key; else a
  rough estimate from the distance, which the message says;
- where it starts (F41d, bug #199): home, unless an event of theirs with a place ends 90
  minutes or less before, the same day ("Drop off kid at in-laws", then the appointment):
  then from there, "leave there around …". `drive_time` can also be told where from;
- the person's "getting ready takes" (default 15 minutes).

The `travel.heads_up` job (every 5 minutes) looks at the next day's events. A rough estimate
(no network) says when an event is close; then the drive is looked up properly, and when
"leave by" minus getting ready has come (up to `SLACK` early), the message goes through the
outbox at once (F38b, bug #191): quiet hours, busy times, the daily limit and pauses don't
hold it, it isn't counted, and one still unsent when the event starts is dropped. One first
seen after getting ready should have started says "start getting ready now". One per
event and start time, so a moved event gets a new one. The person can switch it off.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING, Any, ClassVar
from zoneinfo import ZoneInfo

from pydantic import Field, field_validator

from themi import clock
from themi.accounts import Member
from themi.accounts.preferences import Preferences
from themi.channels.outbox import TRAVEL_KIND, Priority
from themi.connectors.travel import (
    Place,
    Route,
    TravelClient,
    TravelError,
    distance_km,
    estimate,
)
from themi.core import keys
from themi.core.calendar_view import CalendarPreferences, Entry
from themi.core.prompts import as_data
from themi.core.tools import ToolAsks, ToolContext, ToolFailed, tool
from themi.core.wording import untitled
from themi.localtime import to_utc_iso
from themi.standard.lists import name_key
from themi.standard.places import NOT_SURE_TEXT, SavedPlace, day_label, named_place
from themi_google.events import When, title_matches, when_words

if TYPE_CHECKING:
    from themi.core.services import Services

log = logging.getLogger(__name__)

LOOK_AHEAD = timedelta(hours=24)
AT_HOME_KM = 0.5  # closer than this is home: nothing to drive to
LEAVE_WORDS = {"leave", "leaving", "head", "heading", "time", "remind", "reminder", "drive"}
FAR_KM = 100  # a place named with no street or town found further away is checked first
MARGIN = timedelta(minutes=45)  # traffic can be worse than the estimate: look early
JOB_EVERY = timedelta(minutes=5)  # how often `travel.heads_up` runs
# Send a little early, never late (F38b): with the job every 5 minutes, a heads-up is queued
# at most this long before getting ready starts. It was 3 minutes, which let one come up to
# 2 minutes late.
SLACK = JOB_EVERY
RETRY_NOT_FOUND = timedelta(days=1)
LOOK_AHEAD_ON_REQUEST = timedelta(days=14)  # as far as calendars are read (K1)
# F41d (bug #199): an event with a place ending this soon before the next is where they'll
# drive from, not home.
BACK_TO_BACK = timedelta(minutes=90)
STOP = timedelta(minutes=15)  # F41d: a drop-off or pick-up, at the stop
# F55a (reply 521): an arrive_by further before the start than this is a misreading.
EARLIEST = timedelta(hours=4)


@dataclass(frozen=True)
class Origin:
    """Where a drive starts: home (no `label`), a place they named, or the event before."""

    place: Place
    label: str = ""  # "Drop off kid at in-laws (790 La Para Ave)"; "" for home

    @property
    def words(self) -> str:
        return f"from {self.label}" if self.label else "from home"


@dataclass(frozen=True)
class Stop:
    """F41d: a stop on the way to an event ("drop off our kid at my in-laws before"), timed
    from the drives, and Themi's own lines on when to leave."""

    starts: datetime
    ends: datetime
    lines: tuple[str, ...]
    keys: tuple[str, ...]  # the leave times the lines name, for F41c


# F62b: "tutoring: 30" (also "tutoring 30 min", "tutoring = 30").
EARLY_LINE = re.compile(r"^\s*(.*?\w)\s*[:=-]?\s*(\d{1,3})\s*(?:m|mins?|minutes?)?\s*$", re.I)


def early_entries(lines: tuple[str, ...]) -> list[tuple[str, int]]:
    """F62b: the (words, minutes early) a member keeps, from their setting's lines."""
    found = []
    for line in lines:
        m = EARLY_LINE.match(line)
        if m:
            found.append((" ".join(m.group(1).split()), int(m.group(2))))
    return found


class TravelPreferences(Preferences):
    """CR7b1: "time to get ready" before events with a place (K4)."""

    module: ClassVar[str] = "travel"
    settings_anchor: ClassVar[str] = "calendars"  # MP5
    getting_ready_minutes: int = 15
    leave_heads_up: bool = True
    be_early_for: tuple[str, ...] = Field(
        (),
        title="Events I like to be early for",
        description="One per line: words in the event's name, then minutes early (tutoring: 30).",
    )

    @field_validator("be_early_for")
    @classmethod
    def _be_early_for(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        kept: dict[str, str] = {}
        for line in (v for v in value if v.strip()):
            m = EARLY_LINE.match(line)
            if m is None:
                raise ValueError(f"{line.strip()!r}: words, then minutes (tutoring: 30)")
            words, minutes = " ".join(m.group(1).split()), int(m.group(2))
            if not 0 <= minutes <= 120:
                raise ValueError("early is between 0 and 120 minutes")
            if minutes and name_key(words):
                kept[name_key(words)] = f"{words}: {minutes}"
            else:
                kept.pop(name_key(words), None)  # 0: not early for these any more
        return tuple(kept.values())

    @field_validator("getting_ready_minutes")
    @classmethod
    def _getting_ready_minutes(cls, value: int) -> int:
        if not (0 <= value <= 120):
            raise ValueError("getting ready takes between 0 and 120 minutes")
        return value


class TravelHeadsUps:
    def __init__(self, services: Services, client: TravelClient) -> None:
        self.services = services
        self.client = client
        self.db = services.store.db

    def install(self) -> None:
        self.services.provide(keys.travel, self)
        self.services.tools.register(drive_time)
        self.services.tools.register(set_event_early)  # F62b
        self.services.outbox.refreshers[TRAVEL_KIND] = self._as_it_stands

    def _as_it_stands(self, member: Member, row: dict[str, Any]) -> str:
        """F49b (bugs #227, #228): a heads-up that couldn't go out until after its leave
        time (Telegram unreachable) says to head out now, not a time already gone."""
        found = LEAVE_AROUND.search(row["text"])
        if found is None or not row["expires_at"]:
            return str(row["text"])
        tz = self._tz()
        day = datetime.fromisoformat(row["expires_at"]).astimezone(tz).date()
        hour = int(found["hour"]) % 12 + (12 if found["half"] == "pm" else 0)
        leave = time(hour, int(found["minute"] or 0))
        if clock.now() < datetime.combine(day, leave, tzinfo=tz):
            return str(row["text"])
        return f"{row['text'][: found.start()]}time to head out{row['text'][found.end() :]}"

    # ----- home -----------------------------------------------------------------------------

    def home(self) -> tuple[str, Place] | None:
        row = self.db.one("SELECT * FROM family_home WHERE id = 1")
        return (row["address"], Place(row["lat"], row["lon"])) if row else None

    async def set_home(self, address: str) -> Place | None:
        """Find the address on the map and keep it; None if it can't be found."""
        address = " ".join(address.split())[:200]
        place = await self.client.geocode(address) if address else None
        if place is None:
            return None
        self.db.execute(
            "INSERT INTO family_home (id, address, lat, lon, set_at) VALUES (1, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET address = excluded.address, lat = excluded.lat, "
            "lon = excluded.lon, set_at = excluded.set_at",
            (address, place.lat, place.lon, to_utc_iso(clock.now())),
        )
        return place

    # ----- the job --------------------------------------------------------------------------

    async def heads_up(self) -> int:
        """Scheduler job: send the heads-ups that are due. Returns how many went."""
        found = self.home()
        reader = self.services.maybe(keys.calendars)
        if found is None or reader is None:
            return 0
        _, home = found
        now = clock.now()
        sent = 0
        for member in self.services.store.list_members():
            if (
                not self.services.store.preferences(member.id, TravelPreferences).leave_heads_up
                or not member.reachable
            ):
                continue
            for entry in reader.entries(member, now, now + LOOK_AHEAD):
                if await self._consider(member, entry, home, now):
                    sent += 1
        return sent

    async def _consider(self, member: Member, entry: Entry, home: Place, now: datetime) -> bool:
        if entry.all_day or entry.video or not entry.location or entry.starts_at <= now:
            return False
        if self._sent(member, entry):
            return False
        ready = timedelta(
            minutes=self.services.store.preferences(
                member.id, TravelPreferences
            ).getting_ready_minutes
        )
        address = self.address_for(member, entry.location)
        place = await self._place(address) if address else None
        if place is None or distance_km(home, place) < AT_HOME_KM:
            return False
        if self._too_far(address or "", home, place) is not None:
            return False
        start, lost, arrive = await self._planned_start(member, entry, home)
        if arrive <= now:
            return False  # F55a: when they wanted to be there has gone; the reply said so
        rough = timedelta(minutes=estimate(start.place, place).minutes)
        if now < arrive - rough - ready - MARGIN:
            return False  # not close yet: no lookup
        try:
            route = await self.client.route(start.place, place, arrive)
        except TravelError as exc:
            log.info("No route to an event for member %s (%s); estimating", member.id, exc)
            route = estimate(start.place, place)
        leave_by = arrive - timedelta(minutes=route.minutes)
        if now < leave_by - ready - SLACK:
            return False
        await self._send(
            member, entry, route.minutes, route.traffic, leave_by, now, start, lost, arrive
        )
        return True

    async def _planned_start(
        self, member: Member, entry: Entry, home: Place
    ) -> tuple[Origin, str, datetime]:
        """Where the drive starts, the place they'd said if it's no longer found, and when to
        be there: what they said for the event (F46c, F46d), else the event just before,
        else home, for its start."""
        kept, early = self._plan_or_place(member, entry)
        start: Origin | None = None
        lost = ""
        if kept:
            said = await self._named_origin(member, kept, entry.starts_at)
            start, lost = (said, "") if isinstance(said, Origin) else (None, kept)
        start = start or await self._before(member, entry) or Origin(home)  # F41d
        return start, lost, entry.starts_at - timedelta(minutes=early)

    async def heads_up_at(self, member: Member, text: str, day: date) -> datetime | None:
        """F46d (bug #219): when the heads-up to get ready comes for an event of theirs that
        day that `text` names (its title's or place's words), or None."""
        found = self.home()
        reader = self.services.maybe(keys.calendars)
        prefs = self.services.store.preferences(member.id, TravelPreferences)
        if found is None or reader is None or not prefs.leave_heads_up:
            return None
        said = {w for w in name_key(text).split() if len(w) > 3 and w not in LEAVE_WORDS}
        tz = self._tz()
        start_of_day = datetime(day.year, day.month, day.day, tzinfo=tz)
        now = clock.now()
        for entry in reader.entries(member, start_of_day, start_of_day + timedelta(days=1)):
            if entry.all_day or entry.video or not entry.location or entry.starts_at <= now:
                continue
            if not said & set(name_key(f"{entry.title} {entry.location}").split()):
                continue
            place = await self._event_place(member, entry, found[1])
            if isinstance(place, str):
                continue
            start, _, arrive = await self._planned_start(member, entry, found[1])
            route = await self._route(start.place, place, arrive)
            leave_by = arrive - timedelta(minutes=route.minutes)
            return leave_by - timedelta(minutes=prefs.getting_ready_minutes)
        return None

    async def _send(
        self, member: Member, entry: Entry, minutes: int, traffic: bool, leave_by: datetime,
        now: datetime, start: Origin | None = None, lost: str = "",
        arrive: datetime | None = None,
    ) -> None:  # fmt: skip
        tz = self._tz()
        how = "with traffic" if traffic else "(a rough guess, without traffic)"
        there = " there" if start is not None and start.label else ""
        ready = timedelta(
            minutes=self.services.store.preferences(
                member.id, TravelPreferences
            ).getting_ready_minutes
        )
        when = (
            f"leave{there} around {_clock(leave_by.astimezone(tz))}"
            if leave_by > now
            else "time to head out"
        )
        if leave_by > now and now > leave_by - ready:
            # F38b: first seen after getting ready should have started (Themi restarted, the
            # event just added): it still goes at once, and says so.
            when += ", so start getting ready now"
        drive = f"{_duration(minutes)} {how}"
        if start is not None and start.label:  # F41d: from the event before
            drive = f"{_duration(minutes)} {start.words} {how}"
        elif lost:  # F46c: where they said wasn't found now
            drive = f"{_duration(minutes)} from home ({_the(lost)} wasn't found) {how}"
        there_by = (
            f", there by {_clock(arrive.astimezone(tz))}{self._early_why(member, entry, arrive)}"
            if arrive is not None and arrive < entry.starts_at
            else ""
        )  # F46d
        text = (
            f"{entry.title} at {_clock(entry.starts_at.astimezone(tz))}{there_by}, about "
            f"{drive}: {when}."
        )
        self.db.execute(
            "INSERT INTO travel_headsups (member_id, event_id, starts_at, sent_at) "
            "VALUES (?, ?, ?, ?)",
            (member.id, self._event_key(entry), to_utc_iso(entry.starts_at), to_utc_iso(now)),
        )
        await self.services.outbox.send(
            member,
            text,
            priority=Priority.NORMAL,
            kind=TRAVEL_KIND,  # F38b: breaks through quiet hours, busy times, limits, pauses
            expires=entry.starts_at,  # still waiting at the start (an outage): of no use then
            dedupe_key=self._dedupe_key(member, entry),
        )

    def _early_why(self, member: Member, entry: Entry, arrive: datetime) -> str:
        """F62b: " (30 min early for tutoring)" when their "be early for" set the time."""
        minutes, words = self.early_by_title(member, entry)
        if not words or entry.starts_at - arrive != timedelta(minutes=minutes):
            return ""
        if self._planned_early(member, entry):
            return ""
        return f" ({minutes} min early for {words})"

    def _dedupe_key(self, member: Member, entry: Entry) -> str:
        """One heads-up per event, start time and plan (F55a: a changed plan's isn't a
        duplicate of the one that went for the old plan)."""
        key = f"travel-{member.id}-{self._event_key(entry)}-{to_utc_iso(entry.starts_at)}"
        origin, early = self._plan_or_place(member, entry)
        if origin or early:
            key += f"-{early}-{name_key(origin)}"
        return key[:300]

    def rough_drive(self, member: Member, entry: Entry) -> int | None:
        """DC3: about how many minutes' drive an event is from home, from places already
        found on the map and the distance alone (no lookup, no traffic), for the day card's
        "leave around" lead-in. None for an event at home, by video, too far, or at a place
        not found yet."""
        if entry.all_day or entry.video or not entry.location:
            return None
        found = self.home()
        address = self.address_for(member, entry.location)
        if found is None or not address:
            return None
        row = self.db.one(
            "SELECT lat, lon, found FROM geocodes WHERE query_key = ?", (name_key(address),)
        )
        if row is None or not row["found"]:
            return None
        home, place = found[1], Place(row["lat"], row["lon"])
        if distance_km(home, place) < AT_HOME_KM or self._too_far(address, home, place):
            return None
        return estimate(home, place).minutes

    # ----- on request (K4b) ------------------------------------------------------------------

    def next_event(self, viewer: Member, words: str) -> tuple[Member, Entry] | None:
        """The soonest upcoming event, among those this person may see, whose title has all
        these words."""
        reader = self.services.maybe(keys.calendars)
        if reader is None:
            return None
        now = clock.now()
        found = [
            (owner, entry)
            for owner in reader.visible_to(viewer)
            for entry in reader.entries(owner, now, now + LOOK_AHEAD_ON_REQUEST)
            if entry.starts_at > now and title_matches(words, entry.title)
        ]
        return min(found, key=lambda f: f[1].starts_at) if found else None

    async def drive_to_event(
        self, viewer: Member, owner: Member, entry: Entry, ctx: ToolContext | None = None,
        start_from: str = "", address: str = "", arrive_by: str = "",
    ) -> str:  # fmt: skip
        """The drive to `entry`, for the model. With `ctx` (the drive_time tool), the leave
        line is also said by Themi itself, word for word (F41c, bug #199: the model cut
        "leave around 12:43 pm, and start getting ready around 12:28 pm" to "Leave at
        12:43 PM.", and then said it again after the plan had changed). `address`: where it
        is, as they said; it wins over the event's place (F46b, bug #217). `arrive_by`
        ("18:15"): when they want to be there, before it starts (F46d, bug #219). Where they
        leave from and when they want to be there are kept with the event (F46c)."""
        found = self.home()
        if found is None:
            raise TravelError("there's no home address yet (the Family page on the website)")
        tz = self._tz()
        whose = "" if owner.id == viewer.id else f"{owner.name}: "
        when = when_words(When(entry.starts_at, entry.ends_at, entry.all_day), tz)
        line = f"{whose}{entry.title}, {when}" + (
            f" (at {entry.location})" if entry.location else ""
        )
        if entry.video:
            return as_data("calendars", line) + "\nThat one is a video call: no drive."
        own = await self._event_place(owner, entry, found[1])
        note = ""
        if address and start_from and self._same_place(viewer, address, start_from):
            address = ""  # F59b (reply 549): where they leave from isn't where they're going
        if address:
            given = await self._given_place(viewer, address, found[1])
            if isinstance(given, str):
                return as_data("calendars", line) + "\n" + given
            place = given
            if isinstance(own, str):  # the calendar's place didn't work: say how to fix it
                note = (
                    f"\nThe calendar has '{entry.location}' for it; change_calendar_event can "
                    "put this address there."
                    if entry.location
                    else "\nThe calendar has no place for it; change_calendar_event can put "
                    "this address there."
                )
        elif isinstance(own, str):
            return as_data("calendars", line) + "\n" + own
        else:
            place = own
        kept, early = self._plan_or_place(owner, entry)
        new_early = self._early(entry, arrive_by) if arrive_by.strip() else None
        said_from = bool(start_from.strip())
        if not said_from and kept:
            start_from = kept  # F46c (bug #218): what they said earlier for this event
        start = await self.origin(viewer, owner, entry, start_from)
        if isinstance(start, str):
            return as_data("calendars", line) + "\n" + start
        if said_from or new_early is not None:
            self._save_plan(
                owner, entry,
                origin=(start_from if start.label else "") if said_from else None,
                early=new_early,
            )  # fmt: skip
        if kept and not said_from:
            note += (
                f"\nFrom {start.label}, as they said earlier for this event; from: 'home' if "
                "they'll leave from home now."
            )
        early = early if new_early is None else new_early
        arrive = entry.starts_at - timedelta(minutes=early)
        if start.place == place:  # F59b: a place to itself is never asked of the map
            raise TravelError(SAME_PLACE)
        route = await self._route(start.place, place, arrive)
        if route.minutes < 1:
            raise TravelError(SAME_PLACE)
        leave_by = arrive - timedelta(minutes=route.minutes)
        ready = leave_by - timedelta(
            minutes=self.services.store.preferences(
                viewer.id, TravelPreferences
            ).getting_ready_minutes
        )
        now = clock.now()
        if arrive <= now:  # F55a: no "leave now" for a time already gone
            plan = (
                f"to be there by {_clock(arrive.astimezone(tz))} they'd have needed to leave "
                f"at {_clock(leave_by.astimezone(tz))}; leaving now gets them there about "
                f"{_clock((now + timedelta(minutes=route.minutes)).astimezone(tz))}"
            )
        elif leave_by <= now:
            plan = "leave now"
        else:
            plan = f"leave around {_clock(leave_by.astimezone(tz))}"
            if ready > now:
                plan += f", and start getting ready around {_clock(ready.astimezone(tz))}"
        if early and arrive > now:
            why = "" if new_early is not None else self._early_why(owner, entry, arrive)
            plan = f"to be there by {_clock(arrive.astimezone(tz))}{why}, {plan}"
        how = "with traffic" if route.traffic else "(a rough guess, without traffic)"
        heads_up = self._heads_up_words(viewer, owner, entry, leave_by, arrive, now)
        if ctx is not None:
            said, leave = self._leave_line(
                whose, entry, route, leave_by, ready, now, how, start, arrive
            )
            ctx.done.append(said)
            ctx.done_keys.append(leave)
        if start.label:
            plan = plan.replace("leave around", "leave there around").replace(
                "to leave at", "to leave there at"
            )
        saved = self.saved_place(owner, address or entry.location or "")
        if saved is not None and (saved.note or saved.hours):  # F57b: e.g. its visiting hours
            told = [saved.note] if saved.note else []
            if saved.hours:
                told = [
                    t.rstrip(".") + "." for t in told
                ]  # F58e: that day's, so a weekday visit isn't timed to a weekend's
                day = entry.starts_at.astimezone(self._tz()).date()
                told.append(f"Hours on {day_label(day)}: {saved.hours_on(day)}.")
            note += "\n" + as_data(
                "memory", f"What they told Themi about {saved.name}: {' '.join(told)}"
            )
        return as_data("calendars", line) + (
            f"\nAbout {_duration(route.minutes)} {start.words} {how}: {plan}.{heads_up}{note}"
        )

    async def _event_place(self, owner: Member, entry: Entry, home: Place) -> Place | str:
        """Where the event is on the map, or why it can't be said."""
        if not entry.location:
            return "That event has no address on the calendar."
        address = self.address_for(owner, entry.location)
        if address is None:
            return NOT_SURE_TEXT.format(phrase=entry.location)
        place = await self._place(address)
        if place is None:
            return "Its address wasn't found on the map."
        if (far := self._too_far(address, home, place)) is not None:
            return far
        return place

    async def _given_place(self, member: Member, said: str, home: Place) -> Place | str:
        """The address they gave for an event (F46b), on the map, or why not."""
        address = self.address_for(member, said)
        if address is None:
            return NOT_SURE_TEXT.format(phrase=said)
        place = await self._place(address)
        if place is None:
            return f"{said} wasn't found on the map. Adding the city might help."
        if (far := self._too_far(address, home, place)) is not None:
            return far
        return place

    def _leave_line(
        self, whose: str, entry: Entry, route: Route, leave_by: datetime, ready: datetime,
        now: datetime, how: str, start: Origin, arrive: datetime | None = None,
    ) -> tuple[str, str]:  # fmt: skip
        """ "ND psych in person at 1 pm: about 17 min with traffic. Leave around 12:43 pm;
        start getting ready around 12:28 pm." and the leave time it names. Every leave time
        says when to start getting ready (Michael, 2026-11-11)."""
        tz = self._tz()
        leave = _clock(leave_by.astimezone(tz))
        head = f"{whose}{entry.title} at {_clock(entry.starts_at.astimezone(tz))}"
        if arrive is not None and arrive < entry.starts_at:  # F46d
            head += f", there by {_clock(arrive.astimezone(tz))}"
        drive = f"about {_duration(route.minutes)} {how}"
        if start.label:  # F41d
            drive = f"about {_duration(route.minutes)} {start.words} {how}"
        there = " there" if start.label else ""
        key = _key(leave)
        if arrive is not None and arrive <= now:  # F55a
            by = _clock(arrive.astimezone(tz))
            head = f"{whose}{entry.title} at {_clock(entry.starts_at.astimezone(tz))}"
            reach = _clock((now + timedelta(minutes=route.minutes)).astimezone(tz))
            return (
                f"{head}: {drive}. To be there by {by} you'd have needed to leave{there} at "
                f"{leave}; leaving now gets you there about {reach}.",
                key,
            )
        if leave_by <= now:
            return f"{head}: {drive}. Time to leave{there} now.", key
        begin = "now" if ready <= now else f"around {_clock(ready.astimezone(tz))}"
        return f"{head}: {drive}. Leave{there} around {leave}; start getting ready {begin}.", key

    def _heads_up_words(
        self, viewer: Member, owner: Member, entry: Entry, leave_by: datetime,
        arrive: datetime, now: datetime,
    ) -> str:  # fmt: skip
        """When the heads-up comes, and to whom: the person whose calendar it's on (bug #24:
        Themi had said there were no advance reminders). F55a (bug #242): never one the job
        won't send."""
        if not self.services.store.preferences(owner.id, TravelPreferences).leave_heads_up:
            return f" {owner.name} has the heads-up switched off."
        if arrive <= now:
            return ""
        if self._sent(owner, entry):
            return " The heads-up to get ready already went."
        at = leave_by - timedelta(
            minutes=self.services.store.preferences(
                owner.id, TravelPreferences
            ).getting_ready_minutes
        )
        if at <= now:
            return ""
        when = _clock(at.astimezone(self._tz()))
        if owner.id == viewer.id:
            return f" The heads-up to get ready comes then, at about {when}."
        return (
            f" The heads-up to get ready goes to {owner.name}, whose calendar it's on, at "
            f"about {when}."
        )

    async def drive_to_address(
        self, address: str, member: Member | None = None, start_from: str = ""
    ) -> str:
        found = self.home()
        if found is None:
            raise TravelError("there's no home address yet (the Family page on the website)")
        said = address
        if member is not None:
            known = self.address_for(member, address)
            if known is None:
                raise ToolFailed(NOT_SURE_TEXT.format(phrase=address))
            address = known
        place = await self._place(address)
        if place is None:
            return f"{address} wasn't found on the map. Adding the city might help."
        if (far := self._too_far(address, found[1], place)) is not None:
            return far
        start: Origin | str = Origin(found[1])
        if start_from and member is not None:  # F41d: from somewhere else
            start = await self._named_origin(member, start_from, clock.now())
            if isinstance(start, str):
                return start
        assert isinstance(start, Origin)
        route = await self._route(start.place, place, clock.now())
        how = "with traffic" if route.traffic else "(a rough guess, without traffic)"
        where = address if said == address else f"{said} ({address})"
        return f"To {where}: about {_duration(route.minutes)} {start.words} {how}, leaving now."

    # ----- where a drive starts (F41d) -----------------------------------------------------

    async def origin(
        self, viewer: Member, owner: Member, entry: Entry, start_from: str = ""
    ) -> Origin | str:
        """Where the drive to `entry` starts: the place they said, else the event of the
        owner's that ends just before it (back to back), else home. Words when the place
        they said can't be found."""
        found = self.home()
        assert found is not None
        if start_from.strip():
            return await self._named_origin(viewer, start_from, entry.starts_at)
        return await self._before(owner, entry) or Origin(found[1])

    async def _named_origin(self, member: Member, said: str, before: datetime) -> Origin | str:
        """`from`: an event's words (one of theirs that day, before `before`), a named place
        ("in-laws") or an address."""
        said = " ".join(said.split())
        found = self.home()
        if found is not None and self.address_for(member, said) == found[0]:
            return Origin(found[1])  # "home"
        event = self._event_before(member, said, before)
        if event is not None and event.location:
            address = self.address_for(member, event.location)
            place = await self._place(address) if address else None
            if place is not None:
                return Origin(place, f"{event.title} ({_short(address or '')})")
        address = self.address_for(member, said)
        if address is None:
            return NOT_SURE_TEXT.format(phrase=said)
        place = await self._place(address)
        if place is None:
            return f"{said} wasn't found on the map. Adding the city might help."
        label = said if address == said else f"{_the(said)} ({_short(address)})"
        return Origin(place, label)

    def _event_before(self, member: Member, words: str, before: datetime) -> Entry | None:
        reader = self.services.maybe(keys.calendars)
        if reader is None:
            return None
        found = [
            entry
            for owner in reader.visible_to(member)
            for entry in reader.entries(owner, before - timedelta(hours=12), before)
            if not entry.all_day and title_matches(words, entry.title)
        ]
        return max(found, key=lambda e: e.ends_at) if found else None

    async def _before(self, owner: Member, entry: Entry) -> Origin | None:
        """The owner's event with a place that ends 90 minutes or less before `entry`
        starts, the same day: they'll drive from there (F41d)."""
        reader = self.services.maybe(keys.calendars)
        home = self.home()
        if reader is None or home is None:
            return None
        tz = self._tz()
        day = entry.starts_at.astimezone(tz).date()
        candidates = [
            e
            for e in reader.entries(owner, entry.starts_at - BACK_TO_BACK, entry.starts_at)
            if not e.all_day and not e.video and e.location
            and e.starts_at < entry.starts_at
            and entry.starts_at - BACK_TO_BACK <= e.ends_at <= entry.starts_at
            and e.ends_at.astimezone(tz).date() == day
            and (e.title, e.starts_at) != (entry.title, entry.starts_at)
        ]  # fmt: skip
        for before in sorted(candidates, key=lambda e: e.ends_at, reverse=True):
            address = self.address_for(owner, before.location)
            place = await self._place(address) if address else None
            if place is None or distance_km(home[1], place) < AT_HOME_KM:
                continue
            return Origin(place, f"{before.title} ({_short(address or '')})")
        return None

    async def stop_before(self, member: Member, words: str, address: str, said: str) -> Stop | str:
        """F41d: a stop at `address` on the way to their next event matching `words`,
        worked back from it: leave the stop in time to drive there, 15 minutes at the stop,
        leave home in time to drive to the stop, and getting ready before that. Words when
        it can't be worked out (the time is then asked, never made up)."""
        found = self.next_event(member, words)
        home = self.home()
        if found is None:
            return f'No upcoming event matches "{words}", so the stop can\'t be timed from it.'
        if home is None:
            return "There's no home address yet, so the drives can't be worked out."
        _, entry = found
        target = self.address_for(member, entry.location) if entry.location else None
        there = await self._place(target) if target else None
        stop = await self._place(address)
        if there is None or stop is None:
            what = entry.title if there is None else said or address
            return f"{what}'s place wasn't found on the map, so the stop can't be timed."
        tz = self._tz()
        onward = await self._route(stop, there, entry.starts_at)
        leave_stop = entry.starts_at - timedelta(minutes=onward.minutes)
        arrive = leave_stop - STOP
        inward = await self._route(home[1], stop, arrive)
        leave_home = arrive - timedelta(minutes=inward.minutes)
        ready = leave_home - timedelta(
            minutes=self.services.store.preferences(
                member.id, TravelPreferences
            ).getting_ready_minutes
        )
        now = clock.now()
        name = _the(said) if said and not any(c.isdigit() for c in said) else _short(address)
        home_part = (
            "Leave home now"
            if leave_home <= now
            else f"Leave home around {_clock(leave_home.astimezone(tz))}"
            + (
                " (start getting ready now)"
                if ready <= now
                else f" (start getting ready around {_clock(ready.astimezone(tz))})"
            )
        )
        line = (
            f"{home_part} to reach {name} by {_clock(arrive.astimezone(tz))}; leave there "
            f"around {_clock(leave_stop.astimezone(tz))} for {entry.title} at "
            f"{_clock(entry.starts_at.astimezone(tz))}."
        )
        keys_said = (_key(_clock(leave_home.astimezone(tz))),
                     _key(_clock(leave_stop.astimezone(tz))))  # fmt: skip
        return Stop(arrive, leave_stop, (line,), keys_said)

    def private_partners(self, viewer: Member) -> list[str]:
        """The others whose event details this person can't see (K1's setting)."""
        return [
            m.name
            for m in self.services.store.list_members()
            if m.id != viewer.id
            and self.services.store.preferences(m.id, CalendarPreferences).calendar_details
            != "partner"
        ]

    def address_for(self, member: Member, location: str) -> str | None:
        """The address to look up for a place they named ("my parent's house": from what
        they told Themi, F29e), the location itself when it's an address, or None for a
        named place no address is known for."""
        home = self.home()
        named = named_place(
            self.db, member, self.services.store.list_members(), location,
            home[0] if home else None,
        )  # fmt: skip
        if named is None:
            return location
        return named.address

    def _same_place(self, member: Member, a: str, b: str) -> bool:
        """F59b: two things they said are one place (the same address once looked up)."""
        first, second = self.address_for(member, a), self.address_for(member, b)
        return first is not None and name_key(first) == name_key(second or "")

    def saved_place(self, member: Member, location: str) -> SavedPlace | None:
        """F57b: the saved place an event's location is (by name or address), or None."""
        home = self.home()
        named = named_place(
            self.db, member, self.services.store.list_members(), location,
            home[0] if home else None,
        )  # fmt: skip
        return named.saved if named is not None else None

    def _too_far(self, address: str, home: Place, place: Place) -> str | None:
        """A phrase with no street number or town found far away is likely another place of
        that name (bug #154: "parent's house" near Oroville)."""
        if any(c.isdigit() for c in address) or "," in address:
            return None
        km = distance_km(home, place)
        if km <= FAR_KM:
            return None
        return (
            f"'{address}' was found on the map {round(km)} km from home, which may be a "
            "different place of that name. Check the address with them first."
        )

    async def _route(self, home: Place, place: Place, arrive_at: datetime) -> Route:
        try:
            return await self.client.route(home, place, arrive_at)
        except TravelError as exc:
            log.info("No route (%s); estimating", exc)
            return estimate(home, place)

    # ----- places ---------------------------------------------------------------------------

    async def _place(self, location: str) -> Place | None:
        key = name_key(location)
        row = self.db.one("SELECT * FROM geocodes WHERE query_key = ?", (key,))
        if row is not None:
            if row["found"]:
                return Place(row["lat"], row["lon"])
            if clock.now() - datetime.fromisoformat(row["fetched_at"]) < RETRY_NOT_FOUND:
                return None
        try:
            place = await self.client.geocode(location)
        except TravelError as exc:
            log.info("Couldn't look up an event's place (%s)", exc)
            return None
        self.db.execute(
            "INSERT INTO geocodes (query_key, lat, lon, found, fetched_at) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(query_key) DO UPDATE SET lat = excluded.lat, lon = excluded.lon, "
            "found = excluded.found, fetched_at = excluded.fetched_at",
            (
                key,
                place.lat if place else None,
                place.lon if place else None,
                int(place is not None),
                to_utc_iso(clock.now()),
            ),
        )
        return place

    # ----- where they said they'd leave from, kept with the event (F46c) -------------------

    def _plan_key(self, entry: Entry) -> tuple[str, str]:
        """The event (its id, else its title: a place changed later keeps it) and its day."""
        key = f"id:{entry.event_id}" if entry.event_id else name_key(entry.title)
        return key[:200], entry.starts_at.astimezone(self._tz()).date().isoformat()

    def _plan_or_place(self, member: Member, entry: Entry) -> tuple[str, int]:
        """`_plan`, with a saved place's minutes early (F57b) when nothing was said for the
        event itself (an arrival at the start, said for the event, reads as unsaid too)."""
        origin, early = self._plan(member, entry)
        if early:
            return origin, early
        if entry.location:
            saved = self.saved_place(member, entry.location)
            if saved is not None:
                early = saved.arrive_early
        return origin, max(early, self.early_by_title(member, entry)[0])  # F62b: the larger

    def _planned_early(self, member: Member, entry: Entry) -> bool:
        """Was a time to be there said for this one event (F46d)? That wins."""
        return bool(self._plan(member, entry)[1])

    def early_by_title(self, member: Member, entry: Entry) -> tuple[int, str]:
        """F62b: the most minutes early their "be early for" words give this event's title,
        and those words ((0, "") when none match). Whole words, in order."""
        title = f" {name_key(entry.title)} "
        lines = self.services.store.preferences(member.id, TravelPreferences).be_early_for
        best = (0, "")
        for words, minutes in early_entries(lines):
            key = name_key(words)
            if key and f" {key} " in title and minutes > best[0]:
                best = (minutes, words)
        return best

    def set_early(self, member: Member, words: str, minutes: int) -> TravelPreferences:
        """F62b: be `minutes` early for events called `words` (0 stops it)."""
        words = " ".join(words.split())
        lines = self.services.store.preferences(member.id, TravelPreferences).be_early_for
        return self.services.store.save_preferences(
            member, member.id, TravelPreferences, be_early_for=(*lines, f"{words}: {minutes}")
        )

    def _plan(self, member: Member, entry: Entry) -> tuple[str, int]:
        """Where they said they'd leave from ('' home or unsaid), and how many minutes before
        the start they want to be there (F46d)."""
        key, day = self._plan_key(entry)
        found = (key, name_key(entry.title)[:200]) if entry.event_id else (key,)
        for each in found:  # F55a: an arrival given when it was added, kept by its title
            row = self.db.one(
                "SELECT origin, arrive_early FROM travel_plans WHERE member_id = ? "
                "AND event_key = ? AND day = ?",
                (member.id, each, day),
            )
            if row:
                return str(row["origin"]), int(row["arrive_early"])
        return "", 0

    def _save_plan(
        self, member: Member, entry: Entry, *, origin: str | None = None,
        early: int | None = None,
    ) -> None:  # fmt: skip
        """Only what's given changes (origin '': from home). Days gone by are dropped."""
        kept, was = self._plan(member, entry)
        key, day = self._plan_key(entry)
        now_origin = " ".join((kept if origin is None else origin).split())
        now_early = was if early is None else early
        if (now_origin, now_early) != (" ".join(kept.split()), was):
            # F55a (bug #242): the heads-up that went was for the old plan; the new one
            # gets its own.
            self.db.execute(
                "DELETE FROM travel_headsups WHERE member_id = ? AND event_id = ? "
                "AND starts_at = ?",
                (member.id, self._event_key(entry), to_utc_iso(entry.starts_at)),
            )
        today = clock.now().astimezone(self._tz()).date().isoformat()
        self.db.execute("DELETE FROM travel_plans WHERE day < ?", (today,))
        self.db.execute(
            "INSERT INTO travel_plans (member_id, event_key, day, origin, arrive_early, "
            "updated_at) VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (member_id, event_key, day) "
            "DO UPDATE SET origin = excluded.origin, arrive_early = excluded.arrive_early, "
            "updated_at = excluded.updated_at",
            (
                member.id, key, day,
                " ".join((kept if origin is None else origin).split()),
                was if early is None else early,
                to_utc_iso(clock.now()),
            ),
        )  # fmt: skip

    def _early(self, entry: Entry, arrive_by: str) -> int:
        return self.early_for(entry.starts_at, arrive_by)

    def early_for(self, starts_at: datetime, arrive_by: str) -> int:
        """Minutes before the start of `arrive_by` ("18:15") on the event's day. F55a (reply
        521): "06:30" for a 6:30 pm start is the evening, read on a 12-hour clock, not 12
        hours early; one that's neither within `EARLIEST` of the start is asked about."""
        tz = self._tz()
        start = starts_at.astimezone(tz)
        try:
            at = time.fromisoformat(arrive_by.strip())
        except ValueError as exc:
            raise ToolFailed("Not timed: arrive_by looks like 18:15.") from exc
        there = start.replace(hour=at.hour, minute=at.minute, second=0, microsecond=0)
        if there > start:
            raise ToolFailed(
                f"Not timed: {_clock(there)} is after it starts ({_clock(start)}). Ask when "
                "they want to be there."
            )
        later = there + timedelta(hours=12)
        if start - there > EARLIEST and at.hour < 12 and later <= start:
            there = later
        if start - there > EARLIEST:
            gap = int((start - there).total_seconds() // 60)
            raise ToolFailed(
                f"Not timed: {_clock(there)} is {_duration(gap)} before it starts "
                f"({_clock(start)}). Ask when they want to be there."
            )
        return int((start - there).total_seconds() // 60)

    def keep_arrival(self, member: Member, title: str, starts_at: datetime, arrive_by: str) -> int:
        """F55a (bug #241): `add_calendar_event`'s arrive_by, kept under the new event's title
        until it has an id (`_plan` looks there too). Returns the minutes early."""
        early = self.early_for(starts_at, arrive_by)
        key = name_key(title)[:200]
        day = starts_at.astimezone(self._tz()).date().isoformat()
        self.db.execute(
            "INSERT INTO travel_plans (member_id, event_key, day, origin, arrive_early, "
            "updated_at) VALUES (?, ?, ?, '', ?, ?) ON CONFLICT (member_id, event_key, day) "
            "DO UPDATE SET arrive_early = excluded.arrive_early, updated_at = excluded.updated_at",
            (member.id, key, day, early, to_utc_iso(clock.now())),
        )
        return early

    # ----- small things ---------------------------------------------------------------------

    def _sent(self, member: Member, entry: Entry) -> bool:
        return bool(
            self.db.one(
                "SELECT 1 FROM travel_headsups WHERE member_id = ? AND event_id = ? "
                "AND starts_at = ?",
                (member.id, self._event_key(entry), to_utc_iso(entry.starts_at)),
            )
        )

    @staticmethod
    def _event_key(entry: Entry) -> str:
        """Title and place; for an untitled event its id (F38a), so two untitled events at
        one place don't share a heads-up."""
        if untitled(entry.title) and entry.event_id:
            return f"id:{entry.event_id}"[:200]
        return name_key(f"{entry.title} {entry.location}")[:200]

    def _tz(self) -> ZoneInfo:
        family = self.services.store.get_family()
        return ZoneInfo(family.timezone if family else "UTC")


# The heads-up's "leave (there) around 5:52 pm[, so start getting ready now]" (`_send`).
LEAVE_AROUND = re.compile(
    r"leave(?: there)? around (?P<hour>\d{1,2})(?::(?P<minute>\d{2}))? (?P<half>[ap]m)"
    r"(?:, so start getting ready now)?"
)


def _clock(moment: datetime) -> str:
    return moment.strftime("%I:%M %p").lstrip("0").replace(":00 ", " ").lower()


def _key(leave: str) -> str:
    """ "12:43 pm" → "12:43": the reply's own "Leave at 12:43." is the same time (F41c)."""
    return leave.rsplit(" ", 1)[0] if ":" in leave else leave


def _short(address: str) -> str:
    """ "790 La Para Ave, Palo Alto, CA 94306" → "790 La Para Ave"."""
    return address.split(",")[0].strip()


def _the(phrase: str) -> str:
    """ "In-laws" → "the in-laws"; "my parent's house" stays."""
    lower = phrase.strip()
    if lower.lower().split(" ", 1)[0] in ("the", "my", "our", "their", "his", "her"):
        return lower
    return f"the {lower[:1].lower()}{lower[1:]}"


def _duration(minutes: int) -> str:
    if minutes < 60:
        return f"{minutes} min"
    hours, rest = divmod(minutes, 60)
    return f"{hours} hr {rest} min" if rest else f"{hours} hr"


WHICH_TEXT = "Which event, or which address?"
SAME_PLACE = (
    "where they leave from and where they're going came out the same place on the map; check "
    "the address"
)
NOT_SURE = re.compile(r"Not sure where '(.+?)' is: ")
ASK_WHERE_TEXT = "I don't have an address for {phrase} yet. What is it?"
ASK_WHICH_TEXT = "Which event or address do you mean?"


def _asks(result: str) -> str:
    """F59a (reply 547): "Not sure where 'in-laws' is" needs an answer from them: the call
    is `asked`, not done, so an empty reply asks it instead of saying "Done."."""
    if (found := NOT_SURE.search(result)) is not None:
        raise ToolAsks(result, ASK_WHERE_TEXT.format(phrase=found.group(1)))
    return result


@tool(
    "drive_time",
    "How long the drive takes, and when to leave: to their next event whose title has these "
    "words (event: 'pediatrics'; timed for arriving at its start, with traffic where it can), "
    "or to an address (address; leaving now). One of the two, the other ''; but with an "
    "event, address is where the event is, only when the calendar doesn't say or they gave "
    "a different one (it wins over the event's place); never where they leave from (that's "
    "from). "
    "from: where they'll leave from, when it isn't home: a place they named ('in-laws'), an "
    "address, or an event's words; '' for home or what they said before for that event (an "
    "event of theirs ending just before is used then); 'home' when they'll leave from home "
    "after all. arrive_by: HH:MM, when they want to be there, if earlier than the start "
    "('arrive at 6:15' for a 6:30 visit: 18:15), '' for the start or what they said before; "
    "it's a 24-hour clock (6:20 in the evening is 18:20); don't move the event for it.",
    {
        "event": {"type": "string"},
        "address": {"type": "string"},
        "from": {"type": "string", "default": ""},
        "arrive_by": {"type": "string", "default": ""},
    },
)
async def drive_time(ctx: ToolContext, args: dict[str, Any]) -> str:
    try:
        return _asks(await _drive_time(ctx, args))
    except ToolFailed as exc:
        if NOT_SURE.search(str(exc)):
            _asks(str(exc))
        if str(exc) == WHICH_TEXT:
            raise ToolAsks(WHICH_TEXT, ASK_WHICH_TEXT) from exc
        raise


async def _drive_time(ctx: ToolContext, args: dict[str, Any]) -> str:
    travel = ctx.services.maybe(keys.travel)
    if travel is None:
        raise ToolFailed("Travel times aren't set up.")
    words, address = str(args["event"]).strip(), " ".join(str(args["address"]).split())
    start_from = " ".join(str(args.get("from") or "").split())
    try:
        if words:
            found = travel.next_event(ctx.member, words)
            if found is None:
                private = travel.private_partners(ctx.member)
                hidden = (
                    f" {' and '.join(private)} keeps calendar details private, so those events "
                    "aren't searched: they can ask, or share the event to the family calendar."
                    if private
                    else ""
                )
                raise ToolFailed(
                    f'No upcoming event of theirs matches "{words}" in the next two weeks.' + hidden
                )
            result = await travel.drive_to_event(
                ctx.member, *found, ctx, start_from, address, str(args.get("arrive_by") or "")
            )
            if ctx.done:  # F41c: the leave line is Themi's own
                result += (
                    f'\nThemi tells them itself, word for word: "{ctx.done[-1]}" Don\'t say '
                    "the times again."
                )
            return result
        if address:
            return await travel.drive_to_address(address, ctx.member, start_from)
    except TravelError as exc:
        raise ToolFailed(f"No drive time: {exc}.") from exc
    raise ToolFailed(WHICH_TEXT)


@tool(
    "set_event_early",
    "Be there early for a kind of event, by words in its title, from now on: 'I like to be "
    "30 minutes early for tutoring' is words 'tutoring', minutes 30. Their leave and "
    "get-ready times for those events count from that. minutes 0 stops it. For one event "
    "only, use drive_time's arrive_by instead; for a place, the place's own minutes early.",
    {
        "words": {"type": "string", "description": "Words in the events' titles."},
        "minutes": {"type": "integer", "description": "Minutes early, 0 to 120."},
    },
)
async def set_event_early(ctx: ToolContext, args: dict[str, Any]) -> str:
    travel = ctx.services.maybe(keys.travel)
    if travel is None:
        raise ToolFailed("Travel times aren't set up.")
    words, minutes = " ".join(str(args["words"]).split()), int(args["minutes"])
    if not name_key(words):
        raise ToolFailed("Which events? Some words from their titles.")
    if not 0 <= minutes <= 120:
        raise ToolFailed("Early is between 0 and 120 minutes.")
    travel.set_early(ctx.member, words, minutes)
    if minutes == 0:
        return f"Done: no extra time for {words} any more."
    return f"Done: I'll plan to have them at {words} {minutes} minutes early."
