"""The wall's chore chart and routines, as the unofficial API has them (C2a).

From cozyla-sdk's notes on the Tasks app: chores and routines share a schedule
(`repeatsEvery` Daily, Weekly or Monthly; `repeatsEveryCounts`; `repeatsIn`
day names or days of the month), dates are `yyyy-MM-dd` and times `HH:mm`.
A chore can be one-off (`repeats` false, from `startDay` to `endDay`). Its
occurrences ("records") are per member per day, `pending`, `completed` or
`expired`. A routine is one member's, for a part of the day.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, time, timedelta
from typing import Any

NO_TIME = "23:59"  # what the app stores when a chore has no time of day
# The app always sends this as the chore's device id.
CHORE_DEVICE_ID = "db3860b5-9178-427a-894e-d9dfed2bcf5b"
CHORE_ICON = "czl_chores_emoji#_#broom#_#🧹"
ROUTINE_ICON = "routine_property_bed"
PARTS = ("Morning", "Afternoon", "Evening")


@dataclass(frozen=True)
class WallSchedule:
    repeats: bool
    every: str = "Daily"  # Daily, Weekly or Monthly
    count: int = 1  # every N days, weeks or months
    days: str = ""  # Weekly: "Tuesday,Saturday"; Monthly: "19"
    start: date | None = None
    end: date | None = None  # a one-off's last day, or a repeating one's when not forever
    forever: bool = True  # repeatsUntil
    due_time: time | None = None


@dataclass(frozen=True)
class Chore:
    uid: str
    name: str
    members: tuple[str, ...]
    kind: str  # Everyone, AnyOne or Rotate
    schedule: WallSchedule
    raw: dict[str, Any] = field(default_factory=dict, compare=False, repr=False)

    def active_on(self, day: date) -> bool:
        """Still running on `day`: forever, or not past its end."""
        s = self.schedule
        if s.repeats and s.forever:
            return True
        return s.end is None or s.end >= day


@dataclass(frozen=True)
class ChoreRecord:
    chore_uid: str
    member: str
    day: date
    status: str  # pending, completed or expired


@dataclass(frozen=True)
class Routine:
    id: int
    member: str
    title: str
    part: str  # Morning, Afternoon or Evening
    schedule: WallSchedule
    raw: dict[str, Any] = field(default_factory=dict, compare=False, repr=False)


@dataclass(frozen=True)
class RoutineRecord:
    routine_id: int
    member: str
    title: str
    part: str
    day: date
    completed: bool


def _day(value: Any) -> date | None:
    return date.fromisoformat(str(value)[:10]) if value else None


def _time(value: Any) -> time | None:
    if not value or value == NO_TIME:
        return None
    return time.fromisoformat(str(value))


def schedule_from(raw: dict[str, Any]) -> WallSchedule:
    return WallSchedule(
        repeats=bool(raw.get("repeats", True)),
        every=str(raw.get("repeatsEvery") or "Daily"),
        count=int(raw.get("repeatsEveryCounts") or 1),
        days=str(raw.get("repeatsIn") or ""),
        start=_day(raw.get("startDay")),
        end=_day(raw.get("endDay")),
        forever=bool(raw.get("repeatsUntil", True)),
        due_time=_time(raw.get("dueTime")),
    )


def schedule_fields(s: WallSchedule) -> dict[str, Any]:
    if s.start is None:
        raise ValueError("a wall schedule needs a start day")
    start = s.start
    # The app wants an end even when it repeats forever; it's ignored then.
    end = s.end or (start if not s.repeats else start + timedelta(days=30))
    return {
        "repeats": s.repeats,
        "repeatsEvery": s.every,
        "repeatsEveryCounts": s.count,
        "repeatsIn": s.days,
        "startDay": start.isoformat(),
        "endDay": end.isoformat(),
        "repeatsUntil": s.forever if s.repeats else False,
        "dueTime": s.due_time.strftime("%H:%M") if s.due_time else NO_TIME,
    }


def chore_from(raw: dict[str, Any]) -> Chore:
    refs = raw.get("memberRefs") or []
    return Chore(
        uid=str(raw["choreUid"]),
        name=str(raw.get("choreName") or ""),
        members=tuple(str(r["memberUid"]) for r in refs if r.get("memberUid")),
        kind=str(raw.get("choreType") or "Everyone"),
        schedule=schedule_from(raw),
        raw=dict(raw),
    )


def chore_body(
    name: str, members: list[str], kind: str, schedule: WallSchedule, raw: dict[str, Any]
) -> dict[str, Any]:
    """Everything create/v1 and update/v1 need: every field, since update keeps none."""
    return {
        "choreName": name[:50],
        "icon": raw.get("icon") or CHORE_ICON,
        "coins": int(raw.get("coins") or 0),
        "choreType": kind,
        "rotateEveryCounts": int(raw.get("rotateEveryCounts") or 1),
        "reminder": -1,  # Themi does the reminding
        "memberUids": members,
        "choreBank": False,
        "choreDeviceId": CHORE_DEVICE_ID,
        "description": str(raw.get("description") or ""),
        **schedule_fields(schedule),
    }


def record_from(raw: dict[str, Any]) -> ChoreRecord:
    return ChoreRecord(
        chore_uid=str(raw["choreUid"]),
        member=str(raw.get("memberUid") or ""),
        day=_day(raw.get("checkDay")) or date.min,
        status=str(raw.get("status") or "pending"),
    )


def routine_from(raw: dict[str, Any]) -> Routine:
    return Routine(
        id=int(raw["id"]),
        member=str(raw.get("memberUid") or ""),
        title=str(raw.get("routineTitle") or ""),
        part=str(raw.get("routineType") or "Morning"),
        schedule=schedule_from({**raw, "repeats": True, "repeatsUntil": True}),
        raw=dict(raw),
    )


def routine_body(
    title: str, part: str, schedule: WallSchedule, raw: dict[str, Any]
) -> dict[str, Any]:
    fields = schedule_fields(schedule)
    return {
        "routineTitle": title[:50],
        "routineType": part,
        "routineIcon": raw.get("routineIcon") or ROUTINE_ICON,
        "coins": int(raw.get("coins") or 0),
        "habitBonusStars": int(raw.get("habitBonusStars") or 0),
        "habitEnabled": int(raw.get("habitEnabled") or 0),
        "repeatsEvery": fields["repeatsEvery"],
        "repeatsEveryCounts": fields["repeatsEveryCounts"],
        "repeatsIn": fields["repeatsIn"],
        "startDay": fields["startDay"],
        "description": str(raw.get("description") or ""),
    }


def routine_record_from(raw: dict[str, Any]) -> RoutineRecord:
    return RoutineRecord(
        routine_id=int(raw.get("routineId") or raw.get("id") or 0),
        member=str(raw.get("memberUid") or ""),
        title=str(raw.get("routineTitle") or ""),
        part=str(raw.get("routineType") or "Morning"),
        day=_day(raw.get("checkDay")) or date.min,
        completed=str(raw.get("status") or "") == "completed",
    )
