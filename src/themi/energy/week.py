"""How Themi sees someone's week (S3), in words, for their own private page.

For each of the next seven days, morning, afternoon and evening get a phrase
("usually a good stretch", "tends to be low"), or say they're quiet hours or
busy. The numbers behind them never leave this package; the page gets words.

A person can correct a part of the week ("Tuesday evenings are usually
better"). That nudges the learned baseline for those hours, the same way an
outcome does, and gently: one correction moves it a little, not all the way.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from themi import clock
from themi.accounts import Member
from themi.energy.model import EnergyModel, hour_of_week, prior
from themi.energy.windows import Projection, Window, windows
from themi.localtime import in_busy_time, in_quiet_hours, to_local, to_utc_iso

PARTS = {"morning": (8, 12), "afternoon": (12, 17), "evening": (17, 21)}
WEEK_WORDS = (
    (40.0, "tends to be low"),
    (50.0, "often a low-ish stretch"),
    (62.0, "usually steady"),
    (75.0, "usually some energy"),
    (math.inf, "usually a good stretch"),
)
CORRECTION_POINTS = 10.0  # how far one correction moves those hours
DAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


@dataclass(frozen=True)
class DayPart:
    part: str  # "morning", "afternoon" or "evening"
    words: str
    first_guess: bool = False  # nothing learned for these hours yet


@dataclass(frozen=True)
class DayView:
    day: date
    parts: list[DayPart] = field(default_factory=list)


@dataclass(frozen=True)
class LearnedFrom:
    replies: int
    remarks: int
    nudges: int

    @property
    def nothing(self) -> bool:
        return not (self.replies or self.remarks or self.nudges)


def _words(capacity: float) -> str:
    for bound, words in WEEK_WORDS:
        if capacity < bound:
            return words
    return WEEK_WORDS[-1][1]  # pragma: no cover - the last bound is infinite


def week_view(model: EnergyModel, member: Member, days: int = 7) -> list[DayView]:
    """The coming week in words, starting today."""
    member = model.store.get_member(member.id)
    tz = ZoneInfo(model.timezone)
    today = to_local(clock.now(), model.timezone).date()
    start = datetime(today.year, today.month, today.day, tzinfo=tz)
    projection = Projection(model, member, start)
    calendar = model.blocks_around(member, start, start + timedelta(days=days))
    views = []
    for offset in range(days):
        day = today + timedelta(days=offset)
        parts = []
        for part, (first, last) in PARTS.items():
            hours = [
                datetime(day.year, day.month, day.day, h, 30, tzinfo=tz) for h in range(first, last)
            ]
            if all(in_quiet_hours(member, h, model.timezone) for h in hours):
                words = "quiet hours"
            elif sum(in_busy_time(member, h, model.timezone) for h in hours) * 2 > len(hours):
                words = "busy (your busy times)"
            elif sum(any(s <= h < e for s, e in calendar) for h in hours) * 2 > len(hours):
                words = "busy on your calendar"
            else:
                open_hours = [h for h in hours if not in_quiet_hours(member, h, model.timezone)]
                level = sum(projection.at(h) for h in open_hours) / len(open_hours)
                words = _words(level)
            learned = model.db.scalar(
                "SELECT COUNT(*) FROM energy_baseline WHERE member_id = ? AND n > 0 "
                f"AND hour_of_week IN ({', '.join('?' for _ in hours)})",
                (member.id, *(hour_of_week(h, model.timezone) for h in hours)),
            )
            parts.append(DayPart(part, words, first_guess=not learned))
        views.append(DayView(day, parts))
    return views


def good_moments(model: EnergyModel, member: Member) -> list[Window]:
    """The windows Themi would use for a nudge in the next day."""
    return windows(model, member, clock.now())


def learned_from(model: EnergyModel, member: Member) -> LearnedFrom:
    db = model.db
    replies = db.scalar(
        "SELECT COUNT(*) FROM energy_signals WHERE member_id = ? AND source = 'message_timing'",
        (member.id,),
    )
    remarks = db.scalar(
        "SELECT COUNT(*) FROM energy_signals WHERE member_id = ? "
        "AND source IN ('text_note', 'day_level')",
        (member.id,),
    )
    nudges = db.scalar(
        "SELECT COUNT(*) FROM prompt_outcomes WHERE member_id = ? AND outcome IS NOT NULL",
        (member.id,),
    )
    return LearnedFrom(int(replies or 0), int(remarks or 0), int(nudges or 0))


def correct(model: EnergyModel, member: Member, weekday: int, part: str, better: bool) -> None:
    """Nudge that part of the week, every week, a little better or worse."""
    if not 0 <= weekday <= 6 or part not in PARTS:
        raise ValueError("that isn't a part of the week")
    first, last = PARTS[part]
    tz = ZoneInfo(model.timezone)
    # Any date with that weekday works for finding the hour of the week.
    monday = date(2026, 1, 5)
    day = monday + timedelta(days=weekday)
    for hour in range(first, last):
        moment = datetime(day.year, day.month, day.day, hour, 30, tzinfo=tz)
        how = hour_of_week(moment, model.timezone)
        cell = model.db.one(
            "SELECT mean, n FROM energy_baseline WHERE member_id = ? AND hour_of_week = ?",
            (member.id, how),
        )
        mean, n = (cell["mean"], cell["n"]) if cell else (prior(how), 0)
        target = mean + (CORRECTION_POINTS if better else -CORRECTION_POINTS)
        model.db.execute(
            "INSERT INTO energy_baseline (member_id, hour_of_week, mean, n, updated_at) "
            "VALUES (?, ?, ?, ?, ?) ON CONFLICT(member_id, hour_of_week) DO UPDATE SET "
            "mean = excluded.mean, n = excluded.n, updated_at = excluded.updated_at",
            (member.id, how, max(0.0, min(100.0, target)), n + 1, to_utc_iso(clock.now())),
        )
