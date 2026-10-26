"""The family's local time, and each member's quiet hours and busy times within it.

Everything is stored in UTC; anything a person experiences (quiet hours,
"today", dinner time) is decided in the family's timezone.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from themi.accounts.models import Member


def to_local(moment: datetime, timezone: str) -> datetime:
    return moment.astimezone(ZoneInfo(timezone))


def to_utc_iso(moment: datetime) -> str:
    """The one way timestamps are written, so stored strings compare correctly."""
    return moment.astimezone(UTC).isoformat()


def start_of_local_day(moment: datetime, timezone: str) -> datetime:
    local = to_local(moment, timezone)
    return local.replace(hour=0, minute=0, second=0, microsecond=0)


def _at(local_day: datetime, clock_time: time) -> datetime:
    return local_day.replace(
        hour=clock_time.hour, minute=clock_time.minute, second=0, microsecond=0
    )


def in_quiet_hours(member: Member, moment: datetime, timezone: str) -> bool:
    start, end = member.quiet_start, member.quiet_end
    if start == end:
        return False  # no quiet hours
    now = to_local(moment, timezone).time()
    if start < end:  # e.g. 13:00 to 15:00
        return start <= now < end
    return now >= start or now < end  # overnight, e.g. 21:30 to 08:00


def quiet_hours_end(member: Member, moment: datetime, timezone: str) -> datetime:
    """When the current quiet stretch ends; `moment` itself if it's not quiet now."""
    if not in_quiet_hours(member, moment, timezone):
        return moment
    local = to_local(moment, timezone)
    end_today = _at(local, member.quiet_end)
    return end_today if end_today > local else end_today + timedelta(days=1)


def in_busy_time(member: Member, moment: datetime, timezone: str) -> bool:
    local = to_local(moment, timezone)
    return any(busy.covers(local) for busy in member.busy_times)


def free_from(
    member: Member,
    moment: datetime,
    timezone: str,
    blocks: Sequence[tuple[datetime, datetime]] = (),
) -> datetime:
    """The first moment at or after `moment` outside quiet hours, busy times and `blocks`
    (busy events from their calendar).

    One can run into another, so this keeps stepping to the end of whatever covers the
    moment until nothing does.
    """
    when = moment
    for _ in range(2 * (len(member.busy_times) + len(blocks)) + 2):
        after_quiet = quiet_hours_end(member, when, timezone)
        local = to_local(after_quiet, timezone)
        covering = [b for b in member.busy_times if b.covers(local)]
        step = _at(local, max(b.end for b in covering)) if covering else after_quiet
        in_event = [end for start, end in blocks if start <= step < end]
        if in_event:
            step = max(in_event)
        if step == when:
            return when
        when = step
    return when


def next_waking_start(member: Member, moment: datetime, timezone: str) -> datetime:
    """The end of the member's next quiet stretch: tomorrow's start of day for them."""
    local = to_local(moment, timezone)
    candidate = _at(local, member.quiet_end)
    while candidate <= local:
        candidate += timedelta(days=1)
    return candidate
