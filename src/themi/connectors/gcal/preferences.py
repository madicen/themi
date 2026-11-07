"""CR7b1: the calendar module's settings for each person, kept apart from the calendar's
code so that what reads them (busy times, travel, day summaries) imports nothing else."""

from __future__ import annotations

from typing import ClassVar

from pydantic import field_validator

from themi.accounts.preferences import Preferences


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
