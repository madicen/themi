"""Travel time and "time to get ready" (K4).

For an event with a place (not a video call, not all day, not at home), a heads-up comes
when it's time to start getting ready: "Dentist at 3, about 35 min with traffic: leave
around 2:20." It's worked out from:

- home: the family's address, found on the map once (`family_home`, the Family page);
- the event's place, found on the map once and remembered (`geocodes`);
- the drive: TomTom with live traffic, arriving at the start, when there's a key; else a
  rough estimate from the distance, which the message says;
- the person's "getting ready takes" (default 15 minutes).

The `travel.heads_up` job (every 5 minutes) looks at the next day's events. A rough estimate
(no network) says when an event is close; then the drive is looked up properly, and when
"leave by" minus getting ready has come, the message goes through the outbox at normal
priority with the leave time as its deadline: quiet hours hold it only until then. One per
event and start time, so a moved event gets a new one. The person can switch it off.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from themi import clock
from themi.accounts import Member
from themi.channels.outbox import Priority
from themi.connectors.gcal.busy import Entry
from themi.connectors.travel import (
    Place,
    Route,
    TravelClient,
    TravelError,
    distance_km,
    estimate,
)
from themi.core.events import When, title_matches, when_words
from themi.core.lists import name_key
from themi.core.prompts import as_data
from themi.core.tools import ToolContext, ToolFailed, tool
from themi.localtime import to_utc_iso

if TYPE_CHECKING:
    from themi.core.services import Services

log = logging.getLogger(__name__)

LOOK_AHEAD = timedelta(hours=24)
AT_HOME_KM = 0.5  # closer than this is home: nothing to drive to
MARGIN = timedelta(minutes=45)  # traffic can be worse than the estimate: look early
SLACK = timedelta(minutes=3)  # the job runs every 5 minutes: send a little early, not late
RETRY_NOT_FOUND = timedelta(days=1)
LOOK_AHEAD_ON_REQUEST = timedelta(days=14)  # as far as calendars are read (K1)


class TravelHeadsUps:
    def __init__(self, services: Services, client: TravelClient) -> None:
        self.services = services
        self.client = client
        self.db = services.store.db

    def install(self) -> None:
        self.services.travel = self
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
        reader = self.services.calendars
        if found is None or reader is None:
            return 0
        _, home = found
        now = clock.now()
        sent = 0
        for member in self.services.store.list_members():
            if not member.leave_heads_up or member.telegram_user_id is None:
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
        ready = timedelta(minutes=member.getting_ready_minutes)
        place = await self._place(entry.location)
        if place is None or distance_km(home, place) < AT_HOME_KM:
            return False
        rough = timedelta(minutes=estimate(home, place).minutes)
        if now < entry.starts_at - rough - ready - MARGIN:
            return False  # not close yet: no lookup
        try:
            route = await self.client.route(home, place, entry.starts_at)
        except TravelError as exc:
            log.info("No route to an event for member %s (%s); estimating", member.id, exc)
            route = estimate(home, place)
        leave_by = entry.starts_at - timedelta(minutes=route.minutes)
        if now < leave_by - ready - SLACK:
            return False
        await self._send(member, entry, route.minutes, route.traffic, leave_by, now)
        return True

    async def _send(
        self, member: Member, entry: Entry, minutes: int, traffic: bool, leave_by: datetime,
        now: datetime,
    ) -> None:  # fmt: skip
        tz = self._tz()
        how = "with traffic" if traffic else "(a rough guess, without traffic)"
        when = (
            f"leave around {_clock(leave_by.astimezone(tz))}"
            if leave_by > now
            else "time to head out"
        )
        text = (
            f"{entry.title} at {_clock(entry.starts_at.astimezone(tz))}, about "
            f"{_duration(minutes)} {how}: {when}."
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
            kind="travel",
            deadline=max(leave_by, now),
            dedupe_key=f"travel-{member.id}-{self._event_key(entry)}-{to_utc_iso(entry.starts_at)}",
        )

    # ----- on request (K4b) ------------------------------------------------------------------

    def next_event(self, viewer: Member, words: str) -> tuple[Member, Entry] | None:
        """The soonest upcoming event, among those this person may see, whose title has all
        these words."""
        reader = self.services.calendars
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

    async def drive_to_event(self, viewer: Member, owner: Member, entry: Entry) -> str:
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
        place = await self._place(entry.location)
        if place is None:
            return as_data("calendars", line) + "\nIts address wasn't found on the map."
        route = await self._route(found[1], place, entry.starts_at)
        leave_by = entry.starts_at - timedelta(minutes=route.minutes)
        ready = leave_by - timedelta(minutes=viewer.getting_ready_minutes)
        now = clock.now()
        if leave_by <= now:
            plan = "leave now"
        else:
            plan = f"leave around {_clock(leave_by.astimezone(tz))}"
            if ready > now:
                plan += f", and start getting ready around {_clock(ready.astimezone(tz))}"
        how = "with traffic" if route.traffic else "(a rough guess, without traffic)"
        heads_up = self._heads_up_words(viewer, owner, leave_by, now)
        return as_data("calendars", line) + (
            f"\nAbout {_duration(route.minutes)} from home {how}: {plan}.{heads_up}"
        )

    def _heads_up_words(
        self, viewer: Member, owner: Member, leave_by: datetime, now: datetime
    ) -> str:
        """When the heads-up comes, and to whom: the person whose calendar it's on (bug #24:
        Themi had said there were no advance reminders)."""
        if not owner.leave_heads_up:
            return f" {owner.name} has the heads-up switched off."
        at = leave_by - timedelta(minutes=owner.getting_ready_minutes)
        if at <= now:
            return ""
        when = _clock(at.astimezone(self._tz()))
        if owner.id == viewer.id:
            return f" The heads-up to get ready comes then, at about {when}."
        return (
            f" The heads-up to get ready goes to {owner.name}, whose calendar it's on, at "
            f"about {when}."
        )

    async def drive_to_address(self, address: str) -> str:
        found = self.home()
        if found is None:
            raise TravelError("there's no home address yet (the Family page on the website)")
        place = await self._place(address)
        if place is None:
            return f"{address} wasn't found on the map. Adding the city might help."
        route = await self._route(found[1], place, clock.now())
        how = "with traffic" if route.traffic else "(a rough guess, without traffic)"
        return f"To {address}: about {_duration(route.minutes)} from home {how}, leaving now."

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
        return name_key(f"{entry.title} {entry.location}")[:200]

    def _tz(self) -> ZoneInfo:
        family = self.services.store.get_family()
        return ZoneInfo(family.timezone if family else "UTC")


def _clock(moment: datetime) -> str:
    return moment.strftime("%I:%M %p").lstrip("0").replace(":00 ", " ").lower()


def _duration(minutes: int) -> str:
    if minutes < 60:
        return f"{minutes} min"
    hours, rest = divmod(minutes, 60)
    return f"{hours} hr {rest} min" if rest else f"{hours} hr"


@tool(
    "drive_time",
    "How long the drive from home takes, and when to leave: to their next event whose title "
    "has these words (event: 'pediatrics'; timed for arriving at its start, with traffic "
    "where it can), or to an address (address; leaving now). One of the two, the other ''.",
    {"event": {"type": "string"}, "address": {"type": "string"}},
)
async def drive_time(ctx: ToolContext, args: dict[str, Any]) -> str:
    travel = ctx.services.travel
    if travel is None:
        raise ToolFailed("Travel times aren't set up.")
    words, address = str(args["event"]).strip(), " ".join(str(args["address"]).split())
    try:
        if words:
            found = travel.next_event(ctx.member, words)
            if found is None:
                raise ToolFailed(
                    f'No upcoming event of theirs matches "{words}" in the next two weeks.'
                )
            return await travel.drive_to_event(ctx.member, *found)
        if address:
            return await travel.drive_to_address(address)
    except TravelError as exc:
        raise ToolFailed(f"No drive time: {exc}.") from exc
    raise ToolFailed("Which event, or which address?")
