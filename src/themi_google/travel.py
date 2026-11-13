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
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, ClassVar
from zoneinfo import ZoneInfo

from pydantic import field_validator

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
from themi.core.tools import ToolContext, ToolFailed, tool
from themi.core.wording import untitled
from themi.localtime import to_utc_iso
from themi.standard.lists import name_key
from themi.standard.places import NOT_SURE_TEXT, named_place
from themi_google.events import When, title_matches, when_words

if TYPE_CHECKING:
    from themi.core.services import Services

log = logging.getLogger(__name__)

LOOK_AHEAD = timedelta(hours=24)
AT_HOME_KM = 0.5  # closer than this is home: nothing to drive to
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


class TravelPreferences(Preferences):
    """CR7b1: "time to get ready" before events with a place (K4)."""

    module: ClassVar[str] = "travel"
    getting_ready_minutes: int = 15
    leave_heads_up: bool = True

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
        start = await self._before(member, entry) or Origin(home)  # F41d: back to back
        rough = timedelta(minutes=estimate(start.place, place).minutes)
        if now < entry.starts_at - rough - ready - MARGIN:
            return False  # not close yet: no lookup
        try:
            route = await self.client.route(start.place, place, entry.starts_at)
        except TravelError as exc:
            log.info("No route to an event for member %s (%s); estimating", member.id, exc)
            route = estimate(start.place, place)
        leave_by = entry.starts_at - timedelta(minutes=route.minutes)
        if now < leave_by - ready - SLACK:
            return False
        await self._send(member, entry, route.minutes, route.traffic, leave_by, now, start)
        return True

    async def _send(
        self, member: Member, entry: Entry, minutes: int, traffic: bool, leave_by: datetime,
        now: datetime, start: Origin | None = None,
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
        text = f"{entry.title} at {_clock(entry.starts_at.astimezone(tz))}, about {drive}: {when}."
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
            dedupe_key=f"travel-{member.id}-{self._event_key(entry)}-{to_utc_iso(entry.starts_at)}",
        )

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
        start_from: str = "",
    ) -> str:  # fmt: skip
        """The drive to `entry`, for the model. With `ctx` (the drive_time tool), the leave
        line is also said by Themi itself, word for word (F41c, bug #199: the model cut
        "leave around 12:43 pm, and start getting ready around 12:28 pm" to "Leave at
        12:43 PM.", and then said it again after the plan had changed)."""
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
        if not entry.location:
            return as_data("calendars", line) + "\nThat event has no address on the calendar."
        address = self.address_for(owner, entry.location)
        if address is None:
            return as_data("calendars", line) + "\n" + NOT_SURE_TEXT.format(phrase=entry.location)
        place = await self._place(address)
        if place is None:
            return as_data("calendars", line) + "\nIts address wasn't found on the map."
        if (far := self._too_far(address, found[1], place)) is not None:
            return as_data("calendars", line) + "\n" + far
        start = await self.origin(viewer, owner, entry, start_from)
        if isinstance(start, str):
            return as_data("calendars", line) + "\n" + start
        route = await self._route(start.place, place, entry.starts_at)
        leave_by = entry.starts_at - timedelta(minutes=route.minutes)
        ready = leave_by - timedelta(
            minutes=self.services.store.preferences(
                viewer.id, TravelPreferences
            ).getting_ready_minutes
        )
        now = clock.now()
        if leave_by <= now:
            plan = "leave now"
        else:
            plan = f"leave around {_clock(leave_by.astimezone(tz))}"
            if ready > now:
                plan += f", and start getting ready around {_clock(ready.astimezone(tz))}"
        how = "with traffic" if route.traffic else "(a rough guess, without traffic)"
        heads_up = self._heads_up_words(viewer, owner, leave_by, now)
        if ctx is not None:
            said, leave = self._leave_line(whose, entry, route, leave_by, ready, now, how, start)
            ctx.done.append(said)
            ctx.done_keys.append(leave)
        if start.label:
            plan = plan.replace("leave around", "leave there around")
        return as_data("calendars", line) + (
            f"\nAbout {_duration(route.minutes)} {start.words} {how}: {plan}.{heads_up}"
        )

    def _leave_line(
        self, whose: str, entry: Entry, route: Route, leave_by: datetime, ready: datetime,
        now: datetime, how: str, start: Origin,
    ) -> tuple[str, str]:  # fmt: skip
        """ "ND psych in person at 1 pm: about 17 min with traffic. Leave around 12:43 pm;
        start getting ready around 12:28 pm." and the leave time it names. Every leave time
        says when to start getting ready (Michael, 2026-11-11)."""
        tz = self._tz()
        leave = _clock(leave_by.astimezone(tz))
        head = f"{whose}{entry.title} at {_clock(entry.starts_at.astimezone(tz))}"
        drive = f"about {_duration(route.minutes)} {how}"
        if start.label:  # F41d
            drive = f"about {_duration(route.minutes)} {start.words} {how}"
        there = " there" if start.label else ""
        key = _key(leave)
        if leave_by <= now:
            return f"{head}: {drive}. Time to leave{there} now.", key
        begin = "now" if ready <= now else f"around {_clock(ready.astimezone(tz))}"
        return f"{head}: {drive}. Leave{there} around {leave}; start getting ready {begin}.", key

    def _heads_up_words(
        self, viewer: Member, owner: Member, leave_by: datetime, now: datetime
    ) -> str:
        """When the heads-up comes, and to whom: the person whose calendar it's on (bug #24:
        Themi had said there were no advance reminders)."""
        if not self.services.store.preferences(owner.id, TravelPreferences).leave_heads_up:
            return f" {owner.name} has the heads-up switched off."
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


@tool(
    "drive_time",
    "How long the drive takes, and when to leave: to their next event whose title has these "
    "words (event: 'pediatrics'; timed for arriving at its start, with traffic where it can), "
    "or to an address (address; leaving now). One of the two, the other ''. from: where "
    "they'll leave from, when it isn't home: a place they named ('in-laws'), an address, or "
    "an event's words; '' for home (an event of theirs ending just before is used then).",
    {
        "event": {"type": "string"},
        "address": {"type": "string"},
        "from": {"type": "string", "default": ""},
    },
)
async def drive_time(ctx: ToolContext, args: dict[str, Any]) -> str:
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
            result = await travel.drive_to_event(ctx.member, *found, ctx, start_from)
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
    raise ToolFailed("Which event, or which address?")
