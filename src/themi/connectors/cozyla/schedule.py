"""Themi's chore schedules and the wall's, both ways (C2a).

The wall can say every N days, every N weeks on given days, and given days of
the month, with a time of day and an end. Themi can say more: "twice a week,
counted from the last time", "the first Monday of the month", "the day before
garbage day". Those go on the wall one round at a time: a one-off chore on the
round's day, moved when the round moves.
"""

from __future__ import annotations

from datetime import date

from themi.connectors.cozyla.chores import WallSchedule
from themi.core.repeat import DAY_NAMES, Repeat


def wall_can_say(rep: Repeat | None) -> bool:
    return rep is not None and rep.anchored and rep.month_position is None


def to_wall(rep: Repeat | None, due_on: date) -> WallSchedule:
    """The wall's schedule for a chore whose current round is due on `due_on`."""
    if rep is None or not wall_can_say(rep):
        at = rep.at if rep is not None else None
        return WallSchedule(False, start=due_on, end=due_on, forever=False, due_time=at)
    if rep.kind == "daily":
        every, days = "Daily", ""
    elif rep.kind == "weekly":
        every, days = "Weekly", ",".join(DAY_NAMES[d] for d in sorted(rep.weekdays))
    else:
        every, days = "Monthly", str(rep.month_day or 1)
    return WallSchedule(
        repeats=True,
        every=every,
        count=rep.every,
        days=days,
        start=rep.start or due_on,
        end=rep.until,
        forever=rep.until is None,
        due_time=rep.at,
    )


def from_wall(schedule: WallSchedule, today: date) -> Repeat | None:
    """Themi's schedule for a wall chore; None for a one-off or one it can't read."""
    if not schedule.repeats:
        return None
    start = schedule.start or today
    until = None if schedule.forever else schedule.end
    at, every = schedule.due_time, max(1, schedule.count)
    if schedule.every == "Daily":
        return Repeat("daily", every=every, at=at, start=start, until=until)
    parts = [p.strip() for p in schedule.days.split(",") if p.strip()]
    if schedule.every == "Weekly":
        names = [n.casefold() for n in DAY_NAMES]
        days = tuple(sorted(names.index(p.casefold()) for p in parts if p.casefold() in names))
        if not days:
            return None
        return Repeat("weekly", every=every, weekdays=days, at=at, start=start, until=until)
    if schedule.every == "Monthly" and parts and parts[0].isdigit():
        # Themi keeps one day of the month; "1,15" keeps the 1st.
        return Repeat(
            "monthly", every=every, month_day=int(parts[0]), at=at, start=start, until=until
        )
    return None
