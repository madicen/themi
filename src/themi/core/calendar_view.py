"""CR10b1: a calendar as everyone sees it, apart from where it comes from: an event's shape,
its one-line form, and each person's calendar preferences. The calendar module (Google,
the Google pack) fills these in; the day summary, travel and feedback read them without
importing the calendar's code.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import ClassVar
from zoneinfo import ZoneInfo

from pydantic import field_validator

from themi.accounts.preferences import Preferences


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
    calendar_id: str = ""
    event_id: str = ""  # with calendar_id: the same event, read through two accounts


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


class CalendarPreferences(Preferences):
    """CR7b1: the calendar module's settings for each person."""

    module: ClassVar[str] = "calendar"
    calendar_details: str = "me"  # who sees their events' details: "me" or "partner" (K1)
    calendar_twins: str = "ask"  # F34e: the same event on two calendars: ask, guess or keep
    setup_note: bool = True  # F29a: an earlier start is noted as set-up time on the event

    @field_validator("calendar_details")
    @classmethod
    def _calendar_details(cls, value: str) -> str:
        if value not in ("me", "partner"):
            raise ValueError("calendar details are for 'me' or 'partner'")
        return value

    @field_validator("calendar_twins")
    @classmethod
    def _calendar_twins(cls, value: str) -> str:
        if value not in ("ask", "guess", "keep"):
            raise ValueError("the same event on two calendars is ask, guess or keep")
        return value
